# Copyright (c) 2012 OpenStack Foundation.
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

from neutron.common import constants
from neutron.common import utils
from neutron import manager
from neutron.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class NatRpcCallbackMixin(object):
    """A mix-in that enable nat agent support in plugin implementations."""
    def _get_agent_id(self, context, host, agent_type):
        """Retrieve and return id of the given host"""
        plugin = manager.NeutronManager.get_plugin()
        filters = dict(host=[host], agent_type=[agent_type])
        agents = plugin.get_agents(context, filters=filters)
        return agents[0]['id']

    def get_active_vservers(self, context, **kwargs):
        """Retrieve and return a list of the active vservers"""
        plugin = manager.NeutronManager.get_plugin()
        ext_ip = kwargs.get('ext_ip', None)
        ext_port = kwargs.get('ext_port', None)
        admin_state_up = kwargs.get('admin_state_up', False)
        filters = dict()
        if ext_ip:
            filters['ext_ip'] = [ext_ip]
        if ext_port:
            filters['ext_port'] = [ext_port]
        if admin_state_up:
            filters['admin_state_up'] = [admin_state_up]
        vservers = plugin.get_vservers(context, filters=filters)
        return vservers

    def update_vserver(self, context, **kwargs):
        """Update vserver."""
        plugin = manager.NeutronManager.get_plugin()
        vserver_id = kwargs.get('vserver_id')
        admin_state_up = kwargs.get('admin_state_up')
        vserver_dict = {'vserver': {'admin_state_up': admin_state_up}}
        vserver = plugin.update_vserver(context, vserver_id, vserver_dict)
        return vserver

    def get_active_vnats(self, context, **kwargs):
        """Retrieve and return a list of the active vnats."""
        plugin = manager.NeutronManager.get_plugin()
        host = kwargs.get('host')
        ext_ip = kwargs.get('ext_ip', None)
        LOG.debug(_('Vnat list requested from %s'), host)
        plugin = manager.NeutronManager.get_plugin()
        if utils.is_extension_supported(
            plugin, constants.NAT_AGENT_SCHEDULER_EXT_ALIAS) and not ext_ip:
            if cfg.CONF.vnat_auto_schedule:
                plugin.auto_schedule_vnats(context, host)
            try:
                vnats = plugin.list_active_vnats_on_active_nat_agent(
                    context, host)
            except:
                vnats = []
                LOG.debug("Nat agent : %s not found", host)
        else:
            filters = dict(admin_state_up=[True],
                           external_ip_address=[ext_ip])
            vnats = plugin.get_vnats(context, filters=filters)
        return vnats

    def get_vnat_info(self, context, **kwargs):
        """Retrieve and return a extended information about a vnat."""
        vnat_id = kwargs.get('vnat_id')
        host = kwargs.get('host')
        LOG.debug(_('Vnat %(vnat_id)s requested from '
                    '%(host)s'), {'vnat_id': vnat_id,
                                  'host': host})
        plugin = manager.NeutronManager.get_plugin()
        vnat = plugin.get_vnat(context, vnat_id)
        return vnat

    def update_vnat(self, context, **kwargs):
        """Update a vnat"""
        plugin = manager.NeutronManager.get_plugin()
        vnat_id = kwargs.get('vnat_id')
        vnat_dict = dict(vnat_id=vnat_id)
        if kwargs.get('vserver_id', None):
            vnat_dict['vserver_id'] = kwargs.get('vserver_id')
        if kwargs.get('fixed_ip', None):
            vnat_dict['fixed_ip'] = kwargs.get('fixed_ip')
        if kwargs.get('fixed_port', None):
            vnat_dict['fixed_port'] = kwargs.get('fixed_port')
        if kwargs.get('ext_ip', None):
            vnat_dict['external_ip_address'] = kwargs.get('ext_ip')
        if kwargs.get('ext_port', None):
            vnat_dict['external_port'] = kwargs.get('ext_port')
        if kwargs.get('vnat_type', None):
            vnat_dict['vnat_type'] = kwargs.get('vnat_type')
        if kwargs.get('device_id', None):
            vnat_dict['device_id'] = kwargs.get('device_id')
        if kwargs.get('tenant_id', None):
            vnat_dict['tenant_id'] = kwargs.get('tenant_id')
        if kwargs.get('port_id', None):
            vnat_dict['port_id'] = kwargs.get('port_id')
        if kwargs.get('status', None):
            vnat_dict['status'] = kwargs.get('status')
        if kwargs.get('admin_state_up', None):
            vnat_dict['admin_state_up'] = kwargs.get('admin_state_up')
        if kwargs.get('gateway', None):
            vnat_dict['gateway'] = kwargs.get('gateway')
        return plugin.update_vnat(context, vnat_id, {'vnat': vnat_dict})

    def create_vnat(self, context, **kwargs):
        """Create new vnat for a device"""
        plugin = manager.NeutronManager.get_plugin()
        port_id = kwargs.get('port_id', None)
        fixed_ip = kwargs.get('fixed_ip')
        fixed_port = kwargs.get('fixed_port', None)
        vnat_type = kwargs.get('vnat_type')
        device_id = kwargs.get('device_id', None)
        tenant_id = kwargs.get('tenant_id', None)
        shared = kwargs.get('shared', False)
        if fixed_ip:
            filters = dict(fixed_ip_address=[fixed_ip])
            if fixed_port:
                filters['fixed_port'] = [fixed_port]
            vnats = plugin.get_vnats(context, filters=filters)
            if not vnats:
                vnat_dict = {'fixed_ip_address': fixed_ip,
                             'fixed_port': fixed_port,
                             'port_id': port_id,
                             'vnat_type': vnat_type,
                             'tenant_id': tenant_id,
                             'device_id': device_id,
                             'shared': shared,
                             'admin_state_up': True}
                vnat = plugin.create_vnat(context, {'vnat': vnat_dict})
            else:
                LOG.debug("VNat already exist!")
                vnat = vnats[0]
                vnat_dict = {'vnat': {'port_id': port_id,
                                      'vnat_type': vnat_type,
                                      'device_id': device_id,
                                      'tenant_id': tenant_id,
                                      'admin_state_up': True}}
                vnat = plugin.update_vnat(context, vnat['id'], vnat_dict)

    def delete_vnat(self, context, **kwargs):
        """Delete a vnat."""
        plugin = manager.NeutronManager.get_plugin()
        vnat_id = kwargs.get('vnat_id')
        plugin.delete_vnat(context, vnat_id)

    def get_vserver(self, context, ext_ip, ext_port):
        """Get vserver info."""
        plugin = manager.NeutronManager.get_plugin()
        vserver = None
        filters = dict(external_ip_address=[ext_ip])
        vservers = plugin.get_vservers(context, filters=filters)
        LOG.debug('%s', vservers)

        for vs in vservers:
            if not vs['admin_state_up']:
                vserver = vs
                plugin.update_vserver(context, vserver['id'],
                                      {'vserver': {"admin_state_up": True}})
                break
            if vs['external_port'] >= ext_port:
                ext_port = vs['external_port']

        if not vserver:
            # No vserver found, create one.
            ext_port = str(int(ext_port) + 1)
            LOG.info("Creating a new virtual server %s:%s",
                     ext_ip, ext_port)
            vserver_dict = {'vserver': {"external_ip_address": ext_ip,
                                        "external_port": ext_port,
                                        "admin_state_up": True}}
            vserver = plugin.create_vserver(context, vserver_dict)

        return vserver

    def add_nat_interface(self, context, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        subnet_id = kwargs.get('subnet_id')
        host = kwargs.get('host')
        use_gateway = kwargs.get('gateway')
        agent_id = self._get_agent_id(context, host, constants.AGENT_TYPE_NAT)
        interface_info = dict(subnet_id=subnet_id,
                              device_id=agent_id,
                              use_gateway=use_gateway)
        port = plugin.add_nat_interface(context, interface_info)
        return port

    def remove_nat_interface(self, context, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        port_id = kwargs.get('port_id')
        plugin.delete_port(context, port_id)

    def get_nat_interfaces(self, context, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        host = kwargs.get('host')
        agent_id = self._get_agent_id(context, host, constants.AGENT_TYPE_NAT)
        filters = dict(device_owner=[constants.DEVICE_OWNER_NAT_INTF],
                       device_id=[agent_id])
        network_id = kwargs.get('network_id', None)
        if network_id:
            filters['network_id'] = [network_id]
        try:
            return plugin.get_ports(context, filters=filters)
        except:
            return []

    def get_subnets(self, context, **kwargs):
        """Get subnets by port ids"""
        plugin = manager.NeutronManager.get_plugin()
        port_ids = kwargs.get('port_ids')
        network_ids = list()
        subnet_list = list()
        for port_id in port_ids:
            port = plugin.get_port(context, port_id)
            if port and port['network_id'] not in network_ids:
                network_ids.append(port['network_id'])
                filters = dict(network_id=[port['network_id']])
                subnets = plugin.get_subnets(context, filters=filters)
                if subnets:
                    subnet_list.append(subnets[0])
        return subnet_list
