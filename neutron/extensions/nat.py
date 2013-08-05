# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 KylinOS, Inc.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# @author: Yingjun Li, KylinOS, Inc.
#

from abc import abstractmethod

from neutron.api import extensions
from neutron.api.v2 import attributes as attr
from neutron.api.v2 import base
from neutron.common import exceptions as qexception
from neutron import manager
from neutron import quota


# NAT Exceptions
class VserverNotFound(qexception.NotFound):
    message = _("Vserver %(vserver_id)s could not be found")


class VserverInUse(qexception.InUse):
    message = _("Vserver %(vserver_id)s still in use")


class VnatNotFound(qexception.NotFound):
    message = _("Vnat %(vnat_id)s could not be found")


def _validate_uuid_or_none(data, valid_values=None):
    if data is None:
        return None
    return attr._validate_regex(data, attr.UUID_PATTERN)

attr.validators['type:uuid_or_none'] = _validate_uuid_or_none


# Attribute Map
RESOURCE_ATTRIBUTE_MAP = {
    'vservers': {
        'id': {'allow_post': False, 'allow_put': False,
               'is_visible': True},
        'admin_state_up': {'allow_post': True, 'allow_put': True,
                           'default': False,
                           'convert_to': attr.convert_to_boolean,
                           'is_visible': True},
        'external_ip_address': {'allow_post': True, 'allow_put': False,
                                'is_visible': True},
        'external_port': {'allow_post': True, 'allow_put': False,
                          'is_visible': True},
    },
    'vnats': {
        'id': {'allow_post': False, 'allow_put': False,
               'is_visible': True},
        'admin_state_up': {'allow_post': True, 'allow_put': True,
                           'default': True,
                           'convert_to': attr.convert_to_boolean,
                           'is_visible': True},
        'vnat_type': {'allow_post': True, 'allow_put': True,
                      'is_visible': True},
        'status': {'allow_post': True, 'allow_put': True,
                   'is_visible': True, 'default': 'INACTIVE'},
        'shared': {'allow_post': True, 'allow_put': True,
                   'is_visible': True, 'default': False},
        'external_ip_address': {'allow_post': True, 'allow_put': True,
                                'is_visible': True, 'default': None},
        'external_port': {'allow_post': True, 'allow_put': True,
                          'is_visible': True, 'default': None},
        'vserver_id': {'allow_post': True, 'allow_put': True,
                       'is_visible': True, 'default': None},
        'port_id': {'allow_post': True, 'allow_put': True,
                    'is_visible': True, 'default': None},
        'device_id': {'allow_post': True, 'allow_put': True,
                      'is_visible': True, 'default': None},
        'fixed_ip_address': {'allow_post': True, 'allow_put': True,
                             'is_visible': True, 'default': None},
        'fixed_port': {'allow_post': True, 'allow_put': True,
                       'is_visible': True, 'default': None},
        'gateway': {'allow_post': True, 'allow_put': True,
                    'is_visible': True, 'default': None},
        'tenant_id': {'allow_post': True, 'allow_put': False,
                      'required_by_policy': True,
                      'is_visible': True}
    },
}


class Nat(object):

    @classmethod
    def get_name(cls):
        return "Neutron NAT"

    @classmethod
    def get_alias(cls):
        return "nat"

    @classmethod
    def get_description(cls):
        return ("NAT abstraction for basic port forwarding"
                " between L2 Neutron networks and access to external"
                " networks via a NAT gateway.")

    @classmethod
    def get_namespace(cls):
        return "http://docs.openstack.org/ext/neutron/nat/api/v1.0"

    @classmethod
    def get_updated(cls):
        return "2012-11-12T10:00:00-00:00"

    @classmethod
    def get_resources(cls):
        """ Returns Ext Resources """
        exts = []
        plugin = manager.NeutronManager.get_plugin()
        for resource_name in ['vserver', 'vnat']:
            collection_name = resource_name + "s"
            params = RESOURCE_ATTRIBUTE_MAP.get(collection_name, dict())

            member_actions = {}

            quota.QUOTAS.register_resource_by_name(resource_name)

            controller = base.create_resource(collection_name,
                                              resource_name,
                                              plugin, params,
                                              member_actions=member_actions)

            ex = extensions.ResourceExtension(collection_name,
                                              controller,
                                              member_actions=member_actions)
            exts.append(ex)

        return exts


class NATPluginBase(object):

    @abstractmethod
    def create_vserver(self, context, vserver):
        pass

    @abstractmethod
    def update_vserver(self, context, id, vserver):
        pass

    @abstractmethod
    def delete_vserver(self, context, id):
        pass

    @abstractmethod
    def get_vserver(self, context, id, fields=None):
        pass

    @abstractmethod
    def get_vservers(self, context, filters=None, fields=None):
        pass

    @abstractmethod
    def add_vserver_port(self, context, vserver_id, port_info):
        pass

    @abstractmethod
    def remove_vserver_port(self, context, vserver_id, port_info):
        pass

    @abstractmethod
    def create_vnat(self, context, vnat):
        pass

    @abstractmethod
    def update_vnat(self, context, id, vnat):
        pass

    @abstractmethod
    def delete_vnat(self, context, id):
        pass

    @abstractmethod
    def get_vnat(self, context, id, fields=None):
        pass

    @abstractmethod
    def get_vnats(self, context, filters=None, fields=None):
        pass
