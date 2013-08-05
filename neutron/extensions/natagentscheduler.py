# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack Foundation.
# All rights reserved.
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

from abc import abstractmethod

from neutron.api import extensions
from neutron.api.v2 import base
from neutron.api.v2 import resource
from neutron.common import constants
from neutron.common import exceptions
from neutron.extensions import agent
from neutron import manager
from neutron import policy
from neutron import wsgi

NAT_VNAT = 'nat-vnat'
NAT_VNATS = NAT_VNAT + 's'
NAT_AGENT = 'nat-agent'
NAT_AGENTS = NAT_AGENT + 's'


class VnatSchedulerController(wsgi.Controller):
    def index(self, request, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        policy.enforce(request.context,
                       "get_%s" % NAT_VNATS,
                       {})
        return plugin.list_vnats_on_nat_agent(
            request.context, kwargs['agent_id'])

    def create(self, request, body, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        policy.enforce(request.context,
                       "create_%s" % NAT_VNAT,
                       {})
        return plugin.add_vnat_to_nat_agent(
            request.context, kwargs['agent_id'], body['vnat_id'])

    def delete(self, request, id, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        policy.enforce(request.context,
                       "delete_%s" % NAT_VNAT,
                       {})
        return plugin.remove_vnat_from_nat_agent(
            request.context, kwargs['agent_id'], id)


class NatAgentsHostingVnatController(wsgi.Controller):
    def index(self, request, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        policy.enforce(request.context,
                       "get_%s" % NAT_AGENTS,
                       {})
        return plugin.list_nat_agents_hosting_vnat(
            request.context, kwargs['vnat_id'])


class Natagentscheduler(extensions.ExtensionDescriptor):
    """Extension class supporting nat agent scheduler.
    """

    @classmethod
    def get_name(cls):
        return "NAT Agent Scheduler"

    @classmethod
    def get_alias(cls):
        return constants.NAT_AGENT_SCHEDULER_EXT_ALIAS

    @classmethod
    def get_description(cls):
        return "Schedule networks among nat agents"

    @classmethod
    def get_namespace(cls):
        return "http://docs.openstack.org/ext/nat_agent_scheduler/api/v1.0"

    @classmethod
    def get_updated(cls):
        return "2013-08-05T10:00:00-00:00"

    @classmethod
    def get_resources(cls):
        """Returns Ext Resources."""
        exts = []
        parent = dict(member_name="agent",
                      collection_name="agents")
        controller = resource.Resource(VnatSchedulerController(),
                                       base.FAULT_MAP)
        exts.append(extensions.ResourceExtension(
            NAT_VNATS, controller, parent))

        parent = dict(member_name="vnat",
                      collection_name="vnats")

        controller = resource.Resource(NatAgentsHostingVnatController(),
                                       base.FAULT_MAP)
        exts.append(extensions.ResourceExtension(
            NAT_VNATS, controller, parent))
        return exts

    def get_extended_resources(self, version):
        return {}


class InvalidNATAgent(agent.AgentNotFound):
    message = _("Agent %(id)s is not a valid NAT Agent or has been disabled")


class VnatHostedByNATAgent(exceptions.Conflict):
    message = _("The network %(vnat_id)s has been already hosted"
                " by the NAT Agent %(agent_id)s.")


class VnatNotHostedByNATAgent(exceptions.Conflict):
    message = _("The network %(vnat_id)s is not hosted"
                " by the NAT agent %(agent_id)s.")


class NatAgentSchedulerPluginBase(object):
    """REST API to operate the NAT agent scheduler.

    All of method must be in an admin context.
    """

    @abstractmethod
    def add_vnat_to_nat_agent(self, context, id, vnat_id):
        pass

    @abstractmethod
    def remove_vnat_from_nat_agent(self, context, id, vnat_id):
        pass

    @abstractmethod
    def list_vnats_on_nat_agent(self, context, id):
        pass

    @abstractmethod
    def list_nat_agents_hosting_vnat(self, context, vnat_id):
        pass
