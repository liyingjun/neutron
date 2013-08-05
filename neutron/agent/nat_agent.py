# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

from __future__ import with_statement
import eventlet
from eventlet import semaphore
import time
import netaddr
import socket
import sys
from oslo.config import cfg

from novaclient.v1_1 import client as nova_client

from neutron.agent.common import config
from neutron.agent.linux import interface
from neutron.agent.linux import utils
from neutron.agent import rpc as agent_rpc
from neutron.agent.linux import nat_manager
from neutron.agent.linux import ip_lib
from neutron.common import constants
from neutron.common import topics
from neutron import context
from neutron import manager
from neutron.openstack.common import importutils
from neutron.openstack.common import log as logging
from neutron.openstack.common import lockutils
from neutron.openstack.common import loopingcall
from neutron.openstack.common import periodic_task
from neutron.openstack.common.rpc import proxy
from neutron.openstack.common import service
from neutron.openstack.common import uuidutils
from neutron import service as neutron_service


LOG = logging.getLogger(__name__)


INTERNAL_DEV_PREFIX = 'qn-'


class NatPluginApi(proxy.RpcProxy):
    """Agent side of the nat agent RPC API.

    API version history:
        1.0 - Initial version.
    """

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic, context):
        super(NatPluginApi, self).__init__(
            topic=topic, default_version=self.BASE_RPC_API_VERSION)
        self.context = context
        self.host = cfg.CONF.host

    def get_vnat_info(self, vnat_id):
        """Make a remote process call to retrieve vnat info."""
        return DictModel(self.call(self.context,
                                   self.make_msg('get_vnat_info',
                                                 vnat_id=vnat_id),
                                   topic=self.topic))

    def get_active_vnats(self, ext_ip=None):
        """Make a remote process call to retrieve the vnats.
        Retrieve vnats by ext_ip, if ext_ip is specified."""
        vnats = self.call(self.context,
                          self.make_msg('get_active_vnats',
                                        host=self.host,
                                        ext_ip=ext_ip),
                          topic=self.topic)
        if vnats:
            return [DictModel(v) for v in vnats]
        else:
            return []

    def get_vserver(self, ext_ip, ext_port):
        """Make a remote process call to retrieve or create a vserver"""
        return DictModel(self.call(self.context,
                                   self.make_msg('get_vserver',
                                                 ext_ip=ext_ip,
                                                 ext_port=ext_port),
                                   topic=self.topic))

    def get_active_vservers(self, ext_ip=None,
                            ext_port=None, admin_state_up=False):
        """Make a remote process call to retrieve the vservers."""
        state = admin_state_up
        vservers = self.call(self.context,
                             self.make_msg('get_active_vservers',
                                           ext_ip=ext_ip,
                                           ext_port=ext_port,
                                           admin_state_up=state),
                             topic=self.topic)
        if vservers:
            return [DictModel(v) for v in vservers]
        else:
            return []

    def update_vserver(self, vserver_id, admin_state_up):
        """Make a remote process call to update vserver."""
        state = admin_state_up
        return DictModel(self.call(self.context,
                                   self.make_msg('update_vserver',
                                                 vserver_id=vserver_id,
                                                 admin_state_up=state),
                                   topic=self.topic))

    def create_vnat(self, fixed_ip, vnat_type, device_id=None, fixed_port=None,
                    port_id=None, tenant_id=None, shared=False):
        """Make a remote process call to create a vnat."""
        self.call(self.context,
                  self.make_msg('create_vnat',
                                fixed_ip=fixed_ip,
                                vnat_type=vnat_type,
                                device_id=device_id,
                                fixed_port=fixed_port,
                                port_id=port_id,
                                shared=shared,
                                tenant_id=tenant_id),
                  topic=self.topic)

    def update_vnat(self, vnat_id, fixed_ip=None, fixed_port=None,
                    ext_ip=None, ext_port=None, vnat_type=None,
                    tenant_id=None, port_id=None, device_id=None,
                    vserver_id=None, status=None, admin_state_up=None,
                    gateway=None):
        """Make a remote process call to update a vnat."""
        admin_state = admin_state_up
        return DictModel(self.call(self.context,
                                   self.make_msg('update_vnat',
                                                 vnat_id=vnat_id,
                                                 fixed_ip=fixed_ip,
                                                 fixed_port=fixed_port,
                                                 ext_ip=ext_ip,
                                                 ext_port=ext_port,
                                                 vnat_type=vnat_type,
                                                 device_id=device_id,
                                                 tenant_id=tenant_id,
                                                 port_id=port_id,
                                                 vserver_id=vserver_id,
                                                 status=status,
                                                 gateway=gateway,
                                                 admin_state_up=admin_state),
                                   topic=self.topic))

    def delete_vnat(self, vnat_id):
        """Make a remote process call to delete a vnat."""
        self.call(self.context,
                  self.make_msg('delete_vnat',
                                vnat_id=vnat_id),
                  topic=self.topic)

    def add_nat_interface(self, subnet_id, gateway=False):
        """Add a interface for nat local gateway."""
        return self.call(self.context,
                         self.make_msg('add_nat_interface',
                                       subnet_id=subnet_id,
                                       host=self.host,
                                       gateway=gateway),
                         topic=self.topic)

    def remove_nat_interface(self, port_id):
        """Make a remote process call to remove a nat interface."""
        return self.call(self.context,
                         self.make_msg('remove_nat_interface',
                                       port_id=port_id),
                         topic=self.topic)

    def get_nat_interfaces(self, network_id=None):
        """Make a remote process call to get a nat interface."""
        return self.call(self.context,
                         self.make_msg('get_nat_interfaces',
                                       network_id=network_id,
                                       host=self.host),
                         topic=self.topic)

    def get_subnets_for_ports(self, port_ids):
        """Make a remote process call to get a subnets list."""
        subnets = self.call(self.context,
                            self.make_msg('get_subnets',
                                          port_ids=port_ids),
                            topic=self.topic)
        return [DictModel(subnet) for subnet in subnets]


class NatAgent(manager.Manager):
    OPTS = [
        cfg.StrOpt('interface_driver',
                   help="The driver used to manage the virtual interface."),
        cfg.StrOpt('nat_manager',
                   default=
                   'neutron.agent.linux.nat_manager.IptablesNatManager',
                   help="The manager used to apply the port nat rules."),
        cfg.StrOpt('local_external_ip', default='127.0.0.1'),
        cfg.StrOpt('local_internal_ip', default='127.0.0.1'),
        cfg.StrOpt('external_port_start', default='10000'),
        cfg.IntOpt('metadata_port',
                   default=9697,
                   help=_("TCP Port used by neutron metadata namespace "
                          "proxy.")),
        cfg.BoolOpt('use_namespaces', default=True,
                    help=_("Allow overlapping IP.")),
        cfg.IntOpt('send_arp_for_ha',
                   default=3,
                   help=_("Send this many gratuitous ARPs for HA setup, "
                          "set it below or equal to 0 to disable this "
                          "feature.")),
        cfg.ListOpt('fixed_ports', default=['22'],
                    help='The fixed ports for vm to nat.'),
        cfg.BoolOpt('console_enabled', default=False,
                    help='Allow console port nat'),
        cfg.StrOpt('console_port', default='6080',
                   help='Local console port for nat.'),
        cfg.StrOpt('user_defined', default=False),
        cfg.ListOpt('user_defined_rules', default=[''],
                    help='User defined rules,'
                         'only created while user_defined is True'),
        cfg.IntOpt('resync_interval',
                   default=3,
                   help="The time in seconds between state poll requests."),
    ]

    def __init__(self, host=None):
        super(NatAgent, self).__init__(host=cfg.CONF.host)
        self.needs_resync = True
        self.conf = cfg.CONF
        self.cache = VnatCache()
        self.host = self.conf.host
        self.root_helper = self.conf.root_helper
        self.vnat_info = list()
        self.compute_hosts = list()
        self.sync_sem = semaphore.Semaphore(1)
        self.ext_ip = self.conf.local_external_ip
        self.ctx = context.get_admin_context_without_session()
        self.plugin_rpc = NatPluginApi(topics.PLUGIN, self.ctx)
        self.uuid = uuidutils.generate_uuid()

        if not self.conf.interface_driver:
            LOG.error(_('You must specify an interface driver'))
            sys.exit(1)
        try:
            self.driver = importutils.import_object(self.conf.interface_driver,
                                                    self.conf)
        except:
            LOG.exception(_("Error importing interface driver '%s'"
                            % self.conf.interface_driver))
            sys.exit(1)

        manager_class = importutils.import_class(self.conf.nat_manager)
        self.nat_manager = manager_class(root_helper=self.root_helper)
        # If using NAT for port mapping, the default gateway is needed.
        self.default_gateway = False
        if manager_class == nat_manager.LvsNatManager:
            self.default_gateway = True
        self.nova_client = nova_client.Client(
            self.conf.admin_user,
            self.conf.admin_password,
            self.conf.admin_tenant_name,
            auth_url=self.conf.auth_url,
            region_name=self.conf.auth_region
        )
        while True:
            try:
                self._first_check()
                break
            except Exception as e:
                LOG.warn("First check failed with error: %s ! "
                         "recheck after 3s." % e)
                time.sleep(3)

    @lockutils.synchronized('agent', 'nat-')
    def vnat_create_end(self, context, payload):
        """Handle the vnat.create.end nofification event."""
        vnat = DictModel(payload['vnat'])
        fixed_ip = vnat.fixed_ip_address
        fixed_port = vnat.fixed_port
        device_id = vnat.device_id
        port_id = getattr(vnat, 'port_id', None)
        gateway = self._get_gateway(port_id=port_id)
        self._process_created_vnat(vnat.id, fixed_ip, fixed_port, gateway,
                                   device_id)

    def _process_created_vnat(self, vnat_id, fixed_ip, fixed_port,
                              gateway, device_id=None):
        ext_ip = self.ext_ip
        ext_port = self.conf.external_port_start
        vserver = self.plugin_rpc.get_vserver(ext_ip, ext_port)
        vserver_id = vserver.id
        ext_port = vserver.external_port
        self.plugin_rpc.update_vnat(vnat_id, ext_ip=ext_ip,
                                    vserver_id=vserver_id,
                                    ext_port=vserver.external_port,
                                    device_id=device_id,
                                    admin_state_up=True,
                                    gateway=gateway,
                                    status='ACTIVE')
        self.nat_manager.add_nat_rule(ext_ip, ext_port, fixed_ip, fixed_port,
                                      gateway)
        self.nat_manager.apply()
        self.needs_resync = True

    def _get_gateway(self, port_id=None):
        gateway = self.conf.local_internal_ip
        if not port_id:
            return gateway
        plugin_rpc = self.plugin_rpc
        subnets = plugin_rpc.get_subnets_for_ports([port_id])
        for subnet in subnets:
            intfs = plugin_rpc.get_nat_interfaces(network_id=subnet.network_id)
            # Gateway not exist, create one
            if not intfs:
                LOG.debug(_("Add gateway interface for "
                            "subnet : %s"), subnet.id)
                intf = plugin_rpc.add_nat_interface(subnet.id,
                        gateway=self.default_gateway)
            else:
                intf = intfs[0]
            intf['subnet'] = subnet
            if intf['status'] == 'DOWN':
                self._set_subnet_info(intf)
                self.internal_network_added(subnet.network_id,
                                            intf['id'],
                                            intf['ip_cidr'],
                                            intf['mac_address'])
            gateway = intf['fixed_ips'][0]['ip_address']
            break
        return gateway

    @lockutils.synchronized('agent', 'nat-')
    def vnat_delete_end(self, context, payload):
        """Handle the vnat.delete.end nofification event."""
        vnat = DictModel(payload['vnat'])
        self._process_deleted_vnat(vnat)

    def _process_deleted_vnat(self, vnat):
        gateway = vnat.gateway
        self.nat_manager.delete_nat_rule(vnat.external_ip_address,
                                         vnat.external_port,
                                         vnat.fixed_ip_address,
                                         vnat.fixed_port,
                                         gateway)
        self.nat_manager.apply()
        self.needs_resync = True

    def _first_check(self):
        # Check nat status
        plugin_rpc = self.plugin_rpc
        self.nat_manager.clear_all_rules()
        if self.conf.user_defined:
            for rule in self.conf.user_defined_rules:
                LOG.debug("User defined rule: %s", rule)
                self.nat_manager.add_user_rule(rule)
        vnats = plugin_rpc.get_active_vnats()
        for vnat in vnats:
            ext_ip = vnat.external_ip_address
            ext_port = vnat.external_port
            fixed_ip = vnat.fixed_ip_address
            fixed_port = vnat.fixed_port
            port_id = getattr(vnat, 'port_id', None)
            gateway = self._get_gateway(port_id=port_id)
            self.nat_manager.add_nat_rule(ext_ip, ext_port,
                                          fixed_ip, fixed_port, gateway)
        self.nat_manager.apply()
        LOG.info("First check finished with success")

    def _sync_vnats_task_body(self, context):
        try:
            plugin_rpc = self.plugin_rpc
            active_vnats = plugin_rpc.get_active_vnats()
            self.vnat_info = active_vnats
            all_vnats = dict()
            port_ids = list()
            for v in plugin_rpc.get_active_vnats(ext_ip=self.ext_ip):
                all_vnats[v.id] = v
            for vnat in active_vnats:
                if vnat.vnat_type == constants.VNAT_TYPE_HYPER:
                    self.compute_hosts.append(vnat.fixed_ip_address)
                if vnat.id in all_vnats:
                    # Pop out the active vnats.
                    if vnat.port_id:
                        port_ids.append(vnat.port_id)
                    all_vnats.pop(vnat.id)
                # process created vnat.
                if not vnat.vserver_id:
                    self._process_created_vnat(vnat.id,
                                               vnat.fixed_ip_address,
                                               vnat.fixed_port)
            for vnat_id in all_vnats:
                # Delete inactive vnats
                plugin_rpc.delete_vnat(vnat_id)

            intf_dict = dict()
            for i in plugin_rpc.get_nat_interfaces():
                intf_dict[i['id']] = i
            subnets = plugin_rpc.get_subnets_for_ports(port_ids)
            for subnet in subnets:
                intfs = plugin_rpc.get_nat_interfaces(
                            network_id=subnet.network_id)
                # Gateway not exist, create one
                if not intfs:
                    LOG.debug(_("Add gateway interface for "
                                "subnet : %s"), subnet.id)
                    intf = plugin_rpc.add_nat_interface(subnet.id,
                                    gateway=self.default_gateway)
                else:
                    intf = intfs[0]
                if intf['id'] in intf_dict:
                    intf_dict.pop(intf['id'])
                intf['subnet'] = subnet
                if intf['status'] == 'DOWN':
                    self._set_subnet_info(intf)
                    self.internal_network_added(subnet.network_id,
                                                intf['id'],
                                                intf['ip_cidr'],
                                                intf['mac_address'])
            for id, intf in intf_dict.iteritems():
                # Remove the inactive gateway
                LOG.debug(_("Remove gateway interface : %s"), id)
                subnet = plugin_rpc.get_subnets_for_ports([id])[0]
                intf['subnet'] = subnet
                self._set_subnet_info(intf)
                self.internal_network_removed(id, intf['ip_cidr'])
                plugin_rpc.remove_nat_interface(id)

            if self.conf.console_enabled:
                computes = self.nova_client.hosts.list_all()
                for c in computes:
                    node = c.host_name
                    try:
                        fixed_ip = socket.gethostbyname(node)
                    except:
                        fixed_ip = node
                    if ((c.service == 'compute') and
                            (fixed_ip not in self.compute_hosts)):
                        LOG.debug("Cast console nat event for "
                                  "compute node: %s", fixed_ip)
                        v_type = constants.VNAT_TYPE_HYPER
                        f_port = self.conf.console_port
                        self.plugin_rpc.create_vnat(fixed_ip=fixed_ip,
                                                    vnat_type=v_type,
                                                    fixed_port=f_port,
                                                    shared=True)
                        self.compute_hosts.append(fixed_ip)
            self.needs_resync = False
        except:
            self.needs_resync = True
            LOG.exception(_('Unable to sync nat agent state.'))

    @periodic_task.periodic_task
    def _sync_vnats_task(self, context):
        """Resync the vnats status at the configured interval."""
        with self.sync_sem:
            if self.needs_resync:
                LOG.info(_('Synchronizing state'))
                self._sync_vnats_task_body(context)

    def _set_subnet_info(self, port):
        ips = port['fixed_ips']
        if not ips:
            raise Exception(_("Router port %s has no IP address") % port['id'])
        if len(ips) > 1:
            LOG.error(_("Ignoring multiple IPs on router port %s"),
                      port['id'])
        prefixlen = netaddr.IPNetwork(port['subnet'].cidr).prefixlen
        port['ip_cidr'] = "%s/%s" % (ips[0]['ip_address'], prefixlen)

    def get_internal_device_name(self, port_id):
        return (INTERNAL_DEV_PREFIX + port_id)[:self.driver.DEV_NAME_LEN]

    def _send_gratuitous_arp_packet(self, interface_name, ip_address):
        if self.conf.send_arp_for_ha > 0:
            arping_cmd = ['arping', '-A', '-U',
                          '-I', interface_name,
                          '-c', self.conf.send_arp_for_ha,
                          ip_address]
            try:
                utils.execute(arping_cmd, check_exit_code=True,
                              root_helper=self.root_helper)
            except Exception as e:
                LOG.error(_("Failed sending gratuitous ARP: %s"), str(e))

    def internal_network_added(self, network_id, port_id,
                               internal_cidr, mac_address):
        interface_name = self.get_internal_device_name(port_id)
        if not ip_lib.device_exists(interface_name,
                                    root_helper=self.root_helper):
            self.driver.plug(network_id, port_id, interface_name, mac_address,
                             prefix=INTERNAL_DEV_PREFIX)
        self.driver.init_l3(interface_name, [internal_cidr])
        ip_address = internal_cidr.split('/')[0]
        self._send_gratuitous_arp_packet(interface_name, ip_address)

    def internal_network_removed(self, port_id, internal_cidr):
        interface_name = self.get_internal_device_name(port_id)
        if ip_lib.device_exists(interface_name, root_helper=self.root_helper):
            self.driver.unplug(interface_name, prefix=INTERNAL_DEV_PREFIX)

    def after_start(self):
        LOG.info(_("Nat agent started"))


class DictModel(object):
    """Convert dict into an object that provides attribute access to values."""
    def __init__(self, d):
        for key, value in d.iteritems():
            if isinstance(value, list):
                value = [DictModel(item) if isinstance(item, dict) else item
                         for item in value]
            elif isinstance(value, dict):
                value = DictModel(value)
            setattr(self, key, value)


class VnatCache(object):
    """Agent cache of the current vnat state."""
    def __init__(self):
        self.cache = {}
        self.port_lookup = {}

    def get_vnat_ids(self):
        return self.cache.keys()

    def get_vnat_by_id(self, vnat_id):
        return self.cache.get(vnat_id)

    def get_vnats_by_port_id(self, port_id):
        vnat_ids = self.port_lookup.get(port_id)
        vnats = []
        if vnat_ids:
            for id in vnat_ids:
                vnats.append(self.cache.get(id))
        return vnats

    def put(self, vnat, port_id):
        if vnat.id in self.cache:
            self.remove(self.cache[vnat.id], port_id)

        self.cache[vnat.id] = vnat

        if port_id in self.port_lookup:
            self.port_lookup[port_id].append(vnat.id)
        else:
            self.port_lookup[port_id] = [vnat.id]

    def remove(self, vnat, port_id):
        if vnat:
            del self.cache[vnat.id]
        vnats = self.port_lookup[port_id]
        for i in range(0, len(vnats) - 1):
            if vnats[i] == vnat.id:
                del self.port_lookup[port_id][i]
        if not self.port_lookup[port_id]:
            del self.port_lookup[port_id]


class NATAgentWithStateReport(NatAgent):
    def __init__(self, host=None):
        super(NATAgentWithStateReport, self).__init__(host=host)
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.PLUGIN)
        self.agent_state = {
            'binary': 'neutron-nat-agent',
            'host': host,
            'topic': topics.NAT_AGENT,
            'configurations': {
                'use_namespaces': cfg.CONF.use_namespaces,
                'interface_driver': self.conf.interface_driver},
            'start_flag': True,
            'agent_type': constants.AGENT_TYPE_NAT}
        report_interval = cfg.CONF.AGENT.report_interval
        if report_interval:
            self.heartbeat = loopingcall.LoopingCall(self._report_state)
            self.heartbeat.start(interval=report_interval)

    def _report_state(self):
        num_vnats = len(self.vnat_info)
        configurations = self.agent_state['configurations']
        configurations['vnats'] = num_vnats
        try:
            ctx = context.get_admin_context_without_session()
            self.state_rpc.report_state(ctx,
                                        self.agent_state)
            self.agent_state.pop('start_flag', None)
        except AttributeError:
            # This means the server does not support report_state
            LOG.warn(_("neutron server does not support state report."
                       " State report for this agent will be disabled."))
            self.heartbeat.stop()
            return
        except Exception:
            LOG.exception(_("Failed reporting state!"))
            return

    def agent_updated(self, context, payload):
        """Handle the agent_updated notification event."""
        self.needs_resync = True
        LOG.info(_("agent_updated by server side %s!"), payload)


def main():
    eventlet.monkey_patch()
    conf = cfg.CONF
    conf.register_opts(NatAgent.OPTS)
    config.register_agent_state_opts_helper(conf)
    config.register_root_helper(conf)
    conf.register_opts(interface.OPTS)
    conf(project='neutron')
    config.setup_logging(conf)
    server = neutron_service.Service.create(
        binary='neutron-nat-agent',
        topic=topics.NAT_AGENT,
        report_interval=cfg.CONF.AGENT.report_interval,
        manager='neutron.agent.nat_agent.NATAgentWithStateReport')
    service.launch(server).wait()
