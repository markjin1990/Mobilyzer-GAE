# Copyright 2012 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# !/usr/bin/python2.4
#

"""Data model for the Mobiperf service."""
from datetime import datetime
import time

__author__ = 'mdw@google.com (Matt Welsh), gavaletz@google.com (Eric Gavaletz)'

import logging
from google.appengine.api import users
from google.appengine.ext import db
from gspeedometer import config
from gspeedometer.helpers import acl
from gspeedometer.helpers import util


class DeviceInfo(db.Model):
    """Represents the static properties of a given device."""

    # The unique ID of this device, also used as the key
    id = db.StringProperty()
    # The owner of the device
    user = db.UserProperty()
    # Manufacturer, model, and OS name
    manufacturer = db.StringProperty()
    model = db.StringProperty()
    os = db.StringProperty()
    # The type allocation code (TAC) that identifies the device model
    tac = db.StringProperty()

    def last_update(self):
        query = self.deviceproperties_set
        query.order('-timestamp')
        try:
            return query.fetch(1)[0]
        except IndexError:
            logging.exception('There are no device properties associated with '
                              'the given device')
            return None

    def num_updates(self):
        query = self.deviceproperties_set
        return query.count()

    def __str__(self):
        return 'DeviceInfo <id %s, user %s, device %s-%s-%s>' % (
            self.id, self.user, self.manufacturer, self.model, self.os)

    def LastUpdateTime(self):
        lastup = self.last_update()
        if not lastup:
            return None
        return lastup.timestamp

    @classmethod
    def GetDeviceListWithAcl(cls, cursor=None):
        """Return a query for devices that can be accessed by the current user."""
        query = cls.all()
        if not acl.UserIsAdmin():
            query.filter('user =', users.get_current_user())
        if cursor:
            query.with_cursor(cursor)
        return query

    @classmethod
    def GetDeviceWithAcl(cls, device_id):
        device = cls.get_by_key_name(device_id)
        if device and (acl.UserIsAdmin() or
                           (acl.UserIsAnonymousAdmin() and device.user is None) or
                               device.user == users.get_current_user()):
            return device
        else:
            raise RuntimeError('User cannot access device %s', device_id)

    def raceStatus(self):
        props = self.latestDeviceProperties()
        if not props:
            return 2
        return props.cpu_race

    def availableResources(self):
        return 1 - self.raceStatus()

    def isAvailable(self):
        ps = self.latestDeviceProperties()
        return ps and not ps.isOld()

    def latestDeviceProperties(self):
        query = self.deviceproperties_set
        query.order('-timestamp')
        device_properties_list = query.fetch(1)
        if not device_properties_list:
            return None
        else:
            ps = device_properties_list[0]
            if ps.isOld():
                return None
            return ps


class DeviceProperties(db.Model):
    """Represents the dynamic properties of a given device."""

    # Reference to the corresponding DeviceInfo
    device_info = db.ReferenceProperty(DeviceInfo)
    # Mobiperf app version
    app_version = db.StringProperty()
    # Timestamp
    timestamp = db.DateTimeProperty(auto_now_add=True)
    # OS version
    os_version = db.StringProperty()
    # Location
    location = db.GeoPtProperty()
    # How location was acquired (e.g., GPS)
    location_type = db.StringProperty()
    # Network type (e.g., WiFi, UMTS, etc.)
    network_type = db.StringProperty()
    # Country code (e.g., US, CA, IT)
    country_code = db.StringProperty()
    # Carrier
    carrier = db.StringProperty()
    # Battery level
    battery_level = db.IntegerProperty()
    # Battery charging status
    is_battery_charging = db.BooleanProperty()
    # Cell information represented as a string in the form of
    # 'LAC,CID,RSSI;LAC,CID,RSSI;...', where each semicolon separated
    # triplet 'LAC,CID,RSSI' are the Location Area Code, cell ID, and RSSI for
    # one of the cell towers in range
    cell_info = db.StringProperty()
    cell_rssi = db.StringProperty()
    # Receive signal strength of the current cellular connection
    rssi = db.IntegerProperty()
    ssid = db.StringProperty()
    bssid = db.StringProperty()
    wifi_ip_address = db.StringProperty()
    # Mobilyzer version
    mobilyzer_version = db.StringProperty()
    # Host apps
    host_apps = db.StringListProperty()
    # Request App
    request_app = db.StringProperty()

    # SmartMobilyzer-specific properties
    # See https://cloud.google.com/appengine/docs/python/datastore/typesandpropertyclasses?hl=en
    cpu_race = db.FloatProperty()
    mem_race = db.FloatProperty()
    network_race = db.FloatProperty()

    assinged = db.BooleanProperty(default=False)
    done = db.BooleanProperty(default=False)

    # GCM registration id
    registration_id = db.StringProperty();

    def JSON_DECODE_location(self, inputval):
        lat = float(inputval['latitude'])
        lon = float(inputval['longitude'])
        self.location = db.GeoPt(lat, lon)

    def JSON_DECODE_timestamp(self, inputval):
        try:
            self.timestamp = util.MicrosecondsSinceEpochToTime(int(inputval))
        except ValueError:
            logging.exception('Error occurs while converting timestamp '
                              '%s to integer', inputval)
            self.timestamp = None

    def isOld(self):
        d = datetime.now() - self.timestamp
        return d.days * 24 * 60 * 60 + d.seconds > 60 + 30

    def __str__(self):
        return 'DeviceProperties <device %s>' % self.device_info


class Task(db.Expando):
    """Represents a measurement task."""
    # When created
    created = db.DateTimeProperty()
    # Who created this task
    user = db.UserProperty()
    # Measurement type
    type = db.StringProperty()
    # Tag for this measurement task
    tag = db.StringProperty()
    # Query filter to match devices against this task
    filter = db.StringProperty()

    # Start and end times
    start_time = db.DateTimeProperty()
    end_time = db.DateTimeProperty()

    # Interval and count
    interval_sec = db.FloatProperty()
    count = db.IntegerProperty()
    # Priority - larger values represent higher priority
    priority = db.IntegerProperty()
    device = db.ReferenceProperty()

    def GetParam(self, key):
        """Return the measurement parameter indexed by the given key."""
        return self._dynamic_properties.get('mparam_' + key, None)

    def Params(self):
        """Return a dict of all measurement parameters."""
        return dict((k[len('mparam_'):], self._dynamic_properties[k])
                    for k in self.dynamic_properties() if k.startswith('mparam_'))

    def JSON_DECODE_parameters(self, input_dict):
        for k, v in input_dict.items():
            setattr(self, 'mparam_' + k, v)

    def GetContext(self, key):
        """Return the measurement contexts indexed by the given key."""
        return self._dynamic_properties.get('mcontext_' + key, None)

    def Contexts(self):
        """Return a dict of all measurement contexts."""
        return dict((k[len('mcontext_'):], self._dynamic_properties[k])
                    for k in self.dynamic_properties() if k.startswith('mcontext_'))

    def JSON_DECODE_contexts(self, input_dict):
        for k, v in input_dict.items():
            setattr(self, 'mcontext_' + k, v)

    def measurmentDone(self, measurment):
        group = self.group
        if group:
            self.done = True
            self.put()
            group.doneTask(self)

    def matchDevice(self, deviceInfo):
        if not self.filter:
            return True
        devices = self.getSupportedDevices()
        for dev in devices:
            if dev and dev.id == deviceInfo.id:
                return True
        return False

    def getSupportedDevices(self):
        if not self.filter:
            return DeviceInfo.all()

        devices = []

        # Match against DeviceProperties
        try:
            matching_device_properties = DeviceProperties.gql(
                'WHERE ' + self.filter)
            devices += [dp.device_info for dp in matching_device_properties]
        except db.BadQueryError:
            logging.warn('Bad filter expression %s', self.filter)

        # Match against DeviceInfo
        try:
            matching_device_info = DeviceInfo.gql(
                'WHERE ' + self.filter)
            devices += matching_device_info
        except db.BadQueryError:
            logging.warn('Bad filter expression %s', self.filter)
        return devices


class Measurement(db.Expando):
    """Represents a single measurement by a single end-user device."""

    # Reference to the corresponding device properties
    device_properties = db.ReferenceProperty(DeviceProperties)
    # Measurement type
    type = db.StringProperty()
    # Timestamp
    timestamp = db.DateTimeProperty(auto_now_add=True)
    # Whether measurement was successful
    success = db.BooleanProperty()
    # Optional corresponding task
    task = db.ReferenceProperty(Task)

    @classmethod
    def GetMeasurementListWithAcl(cls, limit=None, device_id=None,
                                  start_time=None, end_time=None,
                                  exclude_errors=True):
        """Return a list of measurements that are accessible by the current user."""
        if device_id:
            try:
                devices = [DeviceInfo.GetDeviceWithAcl(device_id)]
            except RuntimeError:
                devices = []
        else:
            devices = list(DeviceInfo.GetDeviceListWithAcl())

        if not devices:
            return []

        results = []
        limit = limit or config.QUERY_FETCH_LIMIT
        per_query_limit = max(1, int(limit / len(devices)))

        for device in devices:
            query = cls.all()
            query.ancestor(device.key())
            if exclude_errors:
                query.filter('success =', True)
            query.order('-timestamp')
            if start_time:
                query.filter('timestamp >=', start_time)
            if end_time:
                query.filter('timestamp <=', end_time)
            for result in query.fetch(per_query_limit):
                results.append(result)
        return results

    def GetTaskID(self):
        try:
            if not self.task:
                return None
            taskid = self.task.key().id()
            return taskid
        except db.ReferencePropertyResolveError:
            logging.exception('Cannot resolve task for measurement %s',
                              self.key().id())
            self.task = None
            # TODO(mdw): Decide if we should do this here. Can be expensive.
            # self.put()
            return None

    def GetParam(self, key):
        """Return the measurement parameter indexed by the given key."""
        return self._dynamic_properties.get('mparam_' + key, None)

    def Params(self):
        """Return a dict of all measurement parameters."""
        return dict((k[len('mparam_'):], self._dynamic_properties[k])
                    for k in self.dynamic_properties() if k.startswith('mparam_'))

    def GetValue(self, key):
        """Return the measurement value indexed by the given key."""
        return self._dynamic_properties.get('mval_' + key, None)

    def Values(self):
        """Return a dict of all measurement values."""
        return dict((k[len('mval_'):], self._dynamic_properties[k]) for
                    k in self.dynamic_properties() if k.startswith('mval_'))

    def JSON_DECODE_timestamp(self, inputval):
        try:
            self.timestamp = util.MicrosecondsSinceEpochToTime(int(inputval))
        except ValueError:
            logging.exception('Error occurs while converting timestamp '
                              '%s to integer', inputval)
            self.timestamp = None

    def JSON_DECODE_parameters(self, input_dict):
        for k, v in input_dict.items():
            if 'content_u_r_l' in k:
                setattr(self, 'mparam_' + k, db.Text(v))
            else:
                setattr(self, 'mparam_' + k, v)

    def JSON_DECODE_values(self, input_dict):
        for k, v in input_dict.items():
            # body, headers, and error messages can be fairly long.
            # Use the Text data type instead
            if k == 'body' or k == 'headers' or k == 'error' or k == 'context_results' or (
                        'navigationTimingResults' in k) or (
                        'resource_' in k) or k == 'tcp_speed_results' or k.startswith(
                "video_"):
                setattr(self, 'mval_' + k, db.Text(v))
            else:
                setattr(self, 'mval_' + k, v)

    def JSON_DECODE_task_key(self, task_key):
        # task_key is optional and can be None.
        # Look up the task_key and set the 'task' field accordingly.
        # If the task does not exist, just don't set this field
        if task_key is None:
            return

        task = Task.get_by_id(int(task_key))
        if not task:
            return
        self.task = task

    def __str__(self):
        return 'Measurement <device %s, type %s>' % (
            self.device_properties, self.type)

    def GetTimestampInZone(self, zone=config.DEFAULT_TIMEZONE):
        if zone and util.TZINFOS[zone]:
            return self.timestamp.replace(
                tzinfo=util.TZINFOS['utc']).astimezone(util.TZINFOS[zone])
        else:
            return self.timestamp


class DeviceTask(db.Model):
    """Represents a task currently assigned to a given device."""
    task = db.ReferenceProperty(Task)
    device_info = db.ReferenceProperty(DeviceInfo)


class ValidationSummary(db.Model):
    """Represents the summary of validation results for a specific
  measurement type during a specific time interval."""
    # measurement type (ping, traceroute, ...)
    measurement_type = db.StringProperty()
    # timestamp representing the end of the observation interval
    timestamp_start = db.DateTimeProperty()
    # timestamp representing the end of the observation interval
    timestamp_end = db.DateTimeProperty(auto_now_add=True)
    # number of total records
    record_count = db.IntegerProperty()
    # number of errors
    error_count = db.IntegerProperty()
    # list of errors and counts
    per_error_count = db.StringListProperty()

    def SetErrorByType(self, error_count_dict):
        """Takes a dict of error names to count of those
    errors, and sets the per_error_count string list 
    property to those values"""
        self.per_error_count = []
        for error, count in error_count_dict.items():
            self.per_error_count.append(('%s:%s' % (error, count)))

    def GetErrorByType(self):
        """Takes the string list property representation of error
    counts and returns the dict representation."""
        error_count_dict = dict()
        for entry in self.per_error_count.items():
            error, count = entry.split(":")
            dict[error] = int(count)
        return error_count_dict


class ValidationEntry(db.Model):
    """Represents details of an invalid measurement result."""
    # reference to the summary it represents
    summary = db.ReferenceProperty(ValidationSummary)
    # reference to the measurement this came from
    measurement = db.ReferenceProperty(Measurement)
    # error types
    error_types = db.StringListProperty()


class RRCInferenceRawData(db.Model):
    """Represents the RRC State model information gathred from the client
     directly"""
    username = db.UserProperty()
    # device IMEI number
    phone_id = db.StringProperty()

    test_id = db.IntegerProperty()

    timestamp = db.DateTimeProperty()
    network_type = db.StringProperty()
    rtt_low = db.IntegerProperty()
    rtt_high = db.IntegerProperty()
    lost_low = db.IntegerProperty()
    lost_high = db.IntegerProperty()
    signal_low = db.IntegerProperty()
    signal_high = db.IntegerProperty()
    error_low = db.IntegerProperty()
    error_high = db.IntegerProperty()
    time_delay = db.IntegerProperty()


class RRCInferenceSizesRawData(db.Model):
    """Represents the data collected on the relationship between round-trip
     times and packet sizes for different RRC states"""
    username = db.UserProperty()
    # device IMEI number
    phone_id = db.StringProperty()

    test_id = db.IntegerProperty()
    timestamp = db.DateTimeProperty()

    network_type = db.StringProperty()
    time_delay = db.IntegerProperty()
    result = db.IntegerProperty()
    size = db.IntegerProperty()


class CDNIpData(db.Model):
    ip = db.StringProperty()
    prefix = db.StringProperty()
    timestamp = db.DateTimeProperty(auto_now=True)
    cdn_domain = db.StringProperty()


class CDNPingMeasurement(db.Model):
    device_id = db.StringProperty()
    timestamp = db.DateTimeProperty(auto_now=True)
    cdn_domain = db.StringProperty()
    ip = db.StringProperty()
    rtt = db.FloatProperty()


class GCMMeasurement(db.Model):
    device_id = db.StringProperty()
    measurement = db.ReferenceProperty(Measurement)
    timestamp = db.DateTimeProperty(auto_now=True)


class RecentMeasurement(db.Model):  # for map visualization
    data = db.TextProperty()
