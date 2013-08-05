# Copyright (c) 2013 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# @author: Yingjun Li, KylinOS, Inc.

from oslo.config import cfg

from neutron.db import models_v2
from neutron.db import nat_rpc_base
from neutron.common import constants
from neutron.common import topics
from neutron.common import utils
from neutron import manager
from neutron.openstack.common import log as logging
from neutron.openstack.common.rpc import proxy


LOG = logging.getLogger(__name__)


class NatAgentNotifyAPI(proxy.RpcProxy):
    """API for plugin to notify nat agent."""
    BASE_RPC_API_VERSION = '1.0'
    VALID_RESOURCES = ['vnat', 'vserver', 'port']
    VALID_METHOD_NAMES = ['vnat.create.end',
                          'vnat.update.end',
                          'vnat.delete.end',
                          'port.create.end',
                          'port.update.end',
                          'port.delete.end',
                          'vserver.create.end',
                          'vserver.update.end',
                          'vserver.delete.end']

    def __init__(self, topic=topics.NAT_AGENT):
        self.nat_rpc_api = nat_rpc_base.NatRpcCallbackMixin()
        super(NatAgentNotifyAPI, self).__init__(
            topic=topic, default_version=self.BASE_RPC_API_VERSION)

    def _get_nat_agents(self, context, vnat_id):
        plugin = manager.NeutronManager.get_plugin()
        nat_agents = plugin.get_nat_agents_hosting_vnats(
            context, [vnat_id], active=True)
        return [(nat_agent.host, nat_agent.topic) for
                nat_agent in nat_agents]

    def _notification_host(self, context, method, vnat, host=None):
        """Notify the agent on host"""
        plugin = manager.NeutronManager.get_plugin()
        if method == 'vnat_create_end':
            port_id = vnat.get('port_id', None)
            network_id = None
            if port_id:
                port = plugin.get_port(context, port_id)
                network_id = port['network_id']
            chosen_agent = plugin.schedule_vnat(context, network_id=network_id)
            if chosen_agent:
                agent_id = chosen_agent['id']
                host = chosen_agent['host']
                plugin.add_vnat_to_nat_agent(context, agent_id, vnat['id'])
                vnat['device_id'] = vnat.get('device_id', agent_id)
                LOG.debug("Create vnat: %s on host: %s", vnat['id'], host)
                self.cast(
                    context, self.make_msg(method,
                                           payload={'vnat': vnat}),
                    topic='%s.%s' % (topics.NAT_AGENT, host))
        if method == 'vnat_delete_end':
            LOG.debug("Delete vnat: %s on host: %s", vnat['id'], host)
            self.cast(
                context, self.make_msg(method,
                                       payload={'vnat': vnat}),
                topic='%s.%s' % (topics.NAT_AGENT, host))

    def _notification(self, context, method, payload):
        """Notify all the agents that are hosting the nat"""
        plugin = manager.NeutronManager.get_plugin()
        if utils.is_extension_supported(
                plugin, constants.NAT_AGENT_SCHEDULER_EXT_ALIAS):
            context = (context if context.is_admin else
                       context.elevated())
            if method == 'port_create_end':
                port = payload['port']
                if port['device_owner'].split(':')[0] != "compute":
                    return
                id = port['id']
                allocated_qry = context.session.query(
                    models_v2.IPAllocation).with_lockmode('update')
                allocated = allocated_qry.filter_by(port_id=id).all()
                subnet = None
                if allocated:
                    for a in allocated:
                        subnet = plugin.get_subnet(context, a['subnet_id'])
                if not subnet:
                    return
                if not subnet['enable_nat']:
                    return
                # Nat all config ports.
                default_ports = cfg.CONF.default_vnat_ports
                for fixed_port in default_ports:
                    # Only nat the first ip of the port
                    fixed_ip = port['fixed_ips'][0]['ip_address']
                    tenant_id = port['tenant_id']
                    device_id = port['device_id']
                    port_id = port['id']
                    vnat_type = constants.VNAT_TYPE_VM
                    self.nat_rpc_api.create_vnat(context,
                                                 port_id=port_id,
                                                 fixed_ip=fixed_ip,
                                                 fixed_port=fixed_port,
                                                 tenant_id=tenant_id,
                                                 device_id=device_id,
                                                 vnat_type=vnat_type)
            if method == 'port_delete_end':
                port_id = payload['port_id']
                filters = dict(port_id=[port_id])
                vnats = plugin.get_vnats(context, filters=filters)
                for vnat in vnats:
                    plugin.delete_vnat(context, vnat['id'])

    def _notification_fanout(self, context, method, payload):
        """Fanout the payload to all nat agents"""
        self.fanout_cast(
            context, self.make_msg(method,
                                   payload=payload),
            topic=topics.NAT_AGENT)

    def vnat_created(self, context, vnat):
        self._notification_host(context, "vnat_create_end", vnat)

    def vnat_deleted(self, context, vnat, host):
        self._notification_host(context, 'vnat_delete_end', vnat, host=host)

    def agent_updated(self, context, admin_state_up, host):
        self._notification_host(context, 'agent_updated',
                                {'admin_state_up': admin_state_up},
                                host=host)

    def notify(self, context, data, methodname):
        # data is {'key' : 'value'} with only one key
        if methodname not in self.VALID_METHOD_NAMES:
            return
        obj_type = data.keys()[0]
        if obj_type not in self.VALID_RESOURCES:
            return
        obj_value = data[obj_type]
        methodname = methodname.replace(".", "_")
        if methodname.endswith("_delete_end"):
            if 'id' in obj_value:
                self._notification(context, methodname,
                                   {obj_type + '_id': obj_value['id']})
        else:
            self._notification(context, methodname, data)

NatAgentNotify = NatAgentNotifyAPI()
