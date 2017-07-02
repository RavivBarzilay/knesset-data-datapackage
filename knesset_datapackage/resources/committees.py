# -*- coding: utf-8 -*-
import logging
import os
import datetime
import csv
from knesset_data.protocols.committee import CommitteeMeetingProtocol
from knesset_datapackage.base import CsvResource, BaseDatapackage, BaseResource, FilesResource, CsvFilesResource
import shutil
from knesset_datapackage.resources.dataservice import BaseKnessetDataServiceCollectionResource
from knesset_data.dataservice.committees import Committee, CommitteeMeeting
from knesset_data.dataservice.mocks import MockCommitteeMeeting



class CommitteesResource(BaseKnessetDataServiceCollectionResource):
    collection = Committee
    object_name = "committee"
    track_generated_objects = False
    collection_getter_kwargs = {
        "committee_ids": "ids",
        "all_committees": "all",
        "main_committees": "main",
    }
    default_getter_type = "active"
    enable_pre_append = True

    def __init__(self, name=None, parent_datapackage_path=None, meetings_resource=None):
        self._meetings_resource = meetings_resource
        super(CommitteesResource, self).__init__(name, parent_datapackage_path)

    def _get_objects_by_main(self, void, proxies=None, **kwargs):
        self.logger.info('fetching main committees')
        self.descriptor["description"] = "main committees"
        return Committee.get_all_active_committees(has_portal_link=True, proxies=proxies)

    def _get_objects_by_active(self, void, proxies=None, **kwargs):
        self.logger.info('fetching active committees')
        self.descriptor["description"] = "active committees"
        return Committee.get_all_active_committees(has_portal_link=False, proxies=proxies)

    def _pre_append(self, committee, **make_kwargs):
        if self._meetings_resource:
            self._meetings_resource.append_for_committee(committee.id, **make_kwargs)


class CommitteeMeetingsResource(CsvResource):
    """
    Committee meetings csv resource - generates the csv with committee meetings for the last DAYS days (default 5 days)
    if __init__ gets a protocols resource it will pass every meeting over to that resource to save the corresponding protocol
    this resource doesn't support making directly, you have to call append_for_committee with a specific committee_id
    """

    def __init__(self, name=None, parent_datapackage_path=None, protocols_resource=None):
        self._protocols_resource = protocols_resource
        json_table_schema = CommitteeMeeting.get_json_table_schema()
        json_table_schema["fields"].append({"type": "string",
                                            "name": "scraper_errors"})
        super(CommitteeMeetingsResource, self).__init__(name, parent_datapackage_path, json_table_schema)

    def _committee_meeting_get(self, committee_id, fromdate, proxies, mock=False):
        cm = CommitteeMeeting if not mock else MockCommitteeMeeting
        return cm.get(committee_id, fromdate, proxies=proxies)

    def append_for_committee(self, committee_id, **make_kwargs):
        if not self._skip_resource(**make_kwargs):
            proxies = make_kwargs.get('proxies', None)
            fromdate = datetime.datetime.now().date() - datetime.timedelta(days=make_kwargs.get('days', 5))
            self.logger.info('appending committee meetings since {} for committee {}'.format(fromdate, committee_id))
            meeting = empty = object()
            for meeting in self._committee_meeting_get(committee_id, fromdate, proxies=proxies, mock=make_kwargs.get("mock", False)):
                if not make_kwargs.get('committee_meeting_ids') or int(meeting.id) in make_kwargs.get('committee_meeting_ids'):
                    scraper_errors = []
                    if self._protocols_resource:
                        try:
                            self._protocols_resource.append_for_meeting(committee_id, meeting.id, meeting.datetime, meeting.protocol, **make_kwargs)
                        except Exception, e:
                            if make_kwargs.get("skip_exceptions"):
                                scraper_errors.append("exception generating protocols resource: {}".format(e))
                                self.logger.warning("exception generating protocols resource for committee {}, meeting {}: {}".format(committee_id, meeting.id, e))
                                self.logger.debug(e, exc_info=1)
                            else:
                                raise
                    self.logger.debug('append committee meeting {}'.format(meeting.id))
                    row = meeting.all_schema_field_values()
                    row["scraper_errors"] = "\n".join(scraper_errors)
                    self._append(row)
                else:
                    meeting = empty
            if meeting == empty:
                self.logger.debug('no meetings')


class CommitteeMeetingProtocolsResource(CsvFilesResource):

    def __init__(self, name, parent_datapackage_path):
        json_table_schema = {"fields": [{"type": "integer", "name": "committee_id"}, #TODO: add connection to atendees csv data file
                                        {"type": "integer", "name": "meeting_id"},
                                        {"type": "string", "name": "text",
                                         "description": "text file containing only the pure text of the protocol (empty in case of error)"},
                                        {"type": "string", "name": "parts",
                                         "description": "csv file with protocol split to speakers (empty in case of error)"},
                                        {"type": "string", "name": "original",
                                         "description": "original file as retrieved from the Knesset (empty in case of error)"},
                                        {"type": "string", "name": "attendees",
                                         "description": "name of attendees scraped from the text of the protocol (empty in case of error)"},
                                        {"type": "string", "name": "scraper_errors",
                                         "description": "comma-separated list of errors received while scraping"}]}
        super(CommitteeMeetingProtocolsResource, self).__init__(name, parent_datapackage_path, json_table_schema,
                                                                file_fields=["text", "parts", "original"])

    def append_for_meeting(self, committee_id, meeting_id, meeting_datetime, meeting_protocol, **make_kwargs):
        if not self._skip_resource(**make_kwargs) and meeting_protocol:
            self.logger.info('appending committee meeting protocols for committe {} meeting {}'.format(committee_id, meeting_id))
            if not os.path.exists(self._base_path):
                os.mkdir(self._base_path)
            # relative paths
            rel_committee_path = "committee_{}".format(committee_id)
            rel_meeting_path = os.path.join(rel_committee_path, "{}_{}".format(meeting_id, str(meeting_datetime).replace(' ', '_').replace(':','-')))
            rel_text_file_path = os.path.join(rel_meeting_path, "protocol.txt")
            rel_parts_file_path = os.path.join(rel_meeting_path, "protocol.csv")
            rel_original_file_path = os.path.join(rel_meeting_path, "original.doc")
            rel_attendees_file_path = os.path.join(rel_meeting_path, "attendees.csv")
            # absolute paths
            abs_committee_path = os.path.join(self._base_path, rel_committee_path)
            abs_meeting_path = os.path.join(self._base_path, rel_meeting_path)
            abs_text_file_path = os.path.join(self._base_path, rel_text_file_path)
            abs_parts_file_path = os.path.join(self._base_path, rel_parts_file_path)
            abs_original_file_path = os.path.join(self._base_path, rel_original_file_path)
            abs_attendees_file_path = os.path.join(self._base_path, rel_attendees_file_path)
            # create directories
            if not os.path.exists(abs_committee_path):
                os.mkdir(abs_committee_path)
            if not os.path.exists(abs_meeting_path):
                os.mkdir(abs_meeting_path)
            # parse the protocol and save
            with meeting_protocol as protocol:
                scraper_errors = []
                # the csv row
                row = {"committee_id": committee_id,
                       "meeting_id": meeting_id,
                       "text": rel_text_file_path.lstrip("/"),
                       "parts": rel_parts_file_path.lstrip("/"),
                       "original": rel_original_file_path.lstrip("/"),
                       "attendees": rel_attendees_file_path.lstrip("/")}
                # original
                try:
                    shutil.copyfile(protocol.file_name, abs_original_file_path)
                except Exception, e:
                    if make_kwargs.get("skip_exceptions"):
                        row["original"] = ""
                        self.logger.warn( "error getting original file for committee {} meeting {}: {}".format(committee_id, meeting_id, e))
                        self.logger.debug(e, exc_info=1)
                        scraper_errors.append("error getting original file: {}".format(e))
                    else:
                        raise
                # text
                with open(abs_text_file_path, 'w') as f:
                    try:
                        f.write(protocol.text.encode('utf8'))
                    except Exception, e:
                        if make_kwargs.get("skip_exceptions"):
                            row["text"] = ""
                            self.logger.warn("error getting text file for committee {} meeting {}: {}".format(committee_id, meeting_id, e))
                            self.logger.debug(e, exc_info=1)
                            scraper_errors.append("error getting text file: {}".format(e))
                        else:
                            raise
                # parts
                with open(abs_parts_file_path, 'wb') as f:
                    csv_writer = csv.writer(f)
                    csv_writer.writerow(["header", "body"])
                    try:
                        for part in protocol.parts:
                            csv_writer.writerow([part.header.encode('utf8'), part.body.encode('utf8')])
                    except Exception, e:
                        if make_kwargs.get("skip_exceptions"):
                            row["parts"] = ""
                            self.logger.warn("error getting parts file for committee {} meeting {}: {}".format(committee_id, meeting_id, e))
                            self.logger.debug(e, exc_info=1)
                            scraper_errors.append("error getting parts file: {}".format(e))
                        else:
                            raise
                
                if protocol.attendees:
                    with open(abs_attendees_file_path, 'wb') as f:
                        csv_writer = csv.writer(f)
                        csv_writer.writerow(["name","role","additional_information"])
                        try:
                            for role in protocol.attendees.keys():
                                if role == "invitees" and protocol.attendees[role]:
                                    for invitee in protocol.attendees[role]:
                                        csv_writer.writerow([invitee["name"].encode("utf-8"),"invitee",invitee["role"].encode("utf-8")])
                                else:
                                    if isinstance(protocol.attendees[role], list):
                                        for attendee in protocol.attendees[role]:
                                            csv_writer.writerow([attendee.encode("utf-8"),role])
                                    elif isinstance(protocol.attendees[role], (str, unicode)):
                                        csv_writer.writerow([protocol.attendees[role].encode("utf-8"),role])
                        except Exception, e:
                            if make_kwargs.get("skip_exceptions"):
                                row["attendees"] = ""
                                self.logger.warn("error getting atrendees file for committee {} meeting {}: {}".format(committee_id, meeting_id, e))
                                self.logger.debug(e, exc_info=1)
                                scraper_errors.append("error getting attendees file: {}".format(e))
                            else:
                                raise


                row["scraper_errors"] = ", ".join(scraper_errors)
                self._append(row, **make_kwargs)
