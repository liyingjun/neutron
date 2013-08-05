# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 KylinOS, Inc.  All rights reserved.
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

import sqlalchemy as sa
from sqlalchemy.orm import exc

from neutron.api.rpc.agentnotifiers import nat_rpc_agent_api
from neutron.api.v2 import attributes
from neutron.common import constants
from neutron.common import exceptions as q_exc
from neutron.db import model_base
from neutron.db import models_v2
from neutron.extensions import nat
from neutron.openstack.common import log as logging
from neutron.openstack.common import uuidutils

LOG = logging.getLogger(__name__)


DEVICE_OWNER_NAT_INTF = constants.DEVICE_OWNER_NAT_INTF


class VSERVER(model_base.BASEV2, models_v2.HasId):
    """Represents a nat vserver.
    """
    external_ip_address = sa.Column(sa.String(64), nullable=False)
    external_port = sa.Column(sa.String(36), nullable=False)
    admin_state_up = sa.Column(sa.Boolean)


class VNAT(model_base.BASEV2, models_v2.HasId, models_v2.HasTenant):
    """Represents a port mapping table, which may or many not be
       allocated to a tenant, and may or may not be associated with
       an internal port/ip address.
    """
    status = sa.Column(sa.String(255))
    admin_state_up = sa.Column(sa.Boolean)
    # vm or hypervisor
    vnat_type = sa.Column(sa.Enum(constants.VNAT_TYPE_VM,
                                  constants.VNAT_TYPE_HYPER,
                                  name='vnat_type'),
                          nullable=False)
    # device id present a vm id or a hypervisor host id
    device_id = sa.Column(sa.String(36))
    external_ip_address = sa.Column(sa.String(64))
    external_port = sa.Column(sa.String(36))
    vserver_id = sa.Column(sa.String(36), sa.ForeignKey('vservers.id'))
    port_id = sa.Column(sa.String(36))
    fixed_ip_address = sa.Column(sa.String(64), nullable=False)
    fixed_port = sa.Column(sa.String(32))
    gateway = sa.Column(sa.String(64))
    shared = sa.Column(sa.Boolean)


class NAT_db_mixin(nat.NATPluginBase):
    """Mixin class to add nat methods to db_plugin_base_v2"""

    def _get_vserver(self, context, id):
        try:
            vserver = self._get_by_id(context, VSERVER, id)
        except exc.NoResultFound:
            raise nat.VserverNotFound(vserver_id=id)
        except exc.MultipleResultsFound:
            LOG.error('Multiple vservers match for %s' % id)
            raise nat.VserverNotFound(vserver_id=id)
        return vserver

    def _make_vserver_dict(self, vserver, fields=None):
        res = {'id': vserver['id'],
               'external_ip_address': vserver['external_ip_address'],
               'admin_state_up': vserver['admin_state_up'],
               'external_port': vserver['external_port']}
        return self._fields(res, fields)

    def get_vserver(self, context, id, fields=None):
        vserver = self._get_vserver(context, id)
        return self._make_vserver_dict(vserver, fields)

    def get_vservers(self, context, filters=None, fields=None,
                     sorts=None, limit=None, marker=None,
                     page_reverse=False):
        marker_obj = self._get_marker_obj(context, 'vserver', limit, marker)
        return self._get_collection(context, VSERVER,
                                    self._make_vserver_dict,
                                    filters=filters, fields=fields,
                                    sorts=sorts,
                                    limit=limit,
                                    marker_obj=marker_obj,
                                    page_reverse=page_reverse)

    def create_vserver(self, context, vserver):
        vs = vserver['vserver']
        if 'fixed_ip_address' in vs:
            del vs['fixed_ip_address']
        if 'fixed_port' in vs:
            del vs['fixed_port']
        with context.session.begin(subtransactions=True):
            vserver_db = VSERVER(id=uuidutils.generate_uuid(),
                                 external_ip_address=vs['external_ip_address'],
                                 admin_state_up=vs['admin_state_up'],
                                 external_port=vs['external_port'])
            context.session.add(vserver_db)
        return self._make_vserver_dict(vserver_db)

    def update_vserver(self, context, id, vserver):
        vs = vserver['vserver']
        if 'fixed_ip_address' in vs:
            del vs['fixed_ip_address']
        if 'fixed_port' in vs:
            del vs['fixed_port']
        with context.session.begin(subtransactions=True):
            vserver_db = self._get_vserver(context, id)
            # Ensure we actually have something to update
            if vs.keys():
                vserver_db.update(vs)
        return self._make_vserver_dict(vserver_db)

    def delete_vserver(self, context, id):
        with context.session.begin(subtransactions=True):
            vserver = self._get_vserver(context, id)

            vserver_filter = {'vserver_id': [id]}
            vnats = self.get_vnats(context, filters=vserver_filter)
            if vnats:
                raise nat.VserverInUse(vserver_id=id)

            context.session.delete(vserver)

    def _get_vnat(self, context, id):
        try:
            vnat = self._get_by_id(context, VNAT, id)
        except exc.NoResultFound:
            raise nat.VnatNotFound(vnat_id=id)
        except exc.MultipleResultsFound:
            LOG.error('Multiple vnat records match for %s' % id)
            raise nat.VnatNotFound(vnat_id=id)
        return vnat

    def _make_vnat_dict(self, vnat, fields=None):
        res = {'id': vnat['id'],
               'tenant_id': vnat['tenant_id'],
               'external_ip_address': vnat['external_ip_address'],
               'external_port': vnat['external_port'],
               'vserver_id': vnat['vserver_id'],
               'status': vnat['status'],
               'admin_state_up': vnat['admin_state_up'],
               'shared': vnat['shared'],
               'vnat_type': vnat['vnat_type'],
               'device_id': vnat['device_id'],
               'port_id': vnat['port_id'],
               'fixed_ip_address': vnat['fixed_ip_address'],
               'gateway': vnat['gateway'],
               'fixed_port': vnat['fixed_port']}
        return self._fields(res, fields)

    def get_vnat(self, context, id, fields=None):
        vnat = self._get_vnat(context, id)
        return self._make_vnat_dict(vnat, fields)

    def get_vnats(self, context, filters=None, fields=None,
                  sorts=None, limit=None, marker=None,
                  page_reverse=False):
        marker_obj = self._get_marker_obj(context, 'vnat', limit, marker)
        return self._get_collection(context, VNAT,
                                    self._make_vnat_dict,
                                    filters=filters, fields=fields,
                                    sorts=sorts,
                                    limit=limit,
                                    marker_obj=marker_obj,
                                    page_reverse=page_reverse)

    def create_vnat(self, context, vnat):
        vn = vnat['vnat']
        tenant_id = self._get_tenant_id_for_create(context, vn)
        if not tenant_id:
            # Use a random uuid for tenant_id
            tenant_id = uuidutils.generate_uuid()
        vn_id = uuidutils.generate_uuid()

        port_id = vn.get('port_id', None)
        fixed_port = vn.get('fixed_port', None)

        external_ip_address = None
        external_port = None
        vserver_id = None
        if 'vserver_id' in vn and vn['vserver_id']:
            vserver_id = vn['vserver_id']
            vserver = self._get_vserver(context, vserver_id)
            external_ip_address = vserver['external_ip_address']
            external_port = vserver['external_port']

        status = vn.get('status', 'ACTIVE')
        shared = vn.get('shared', False)
        vnat_filter = {'fixed_ip_address': [vn['fixed_ip_address']],
                       'fixed_port': [vn['fixed_port']]}
        vnats = self.get_vnats(context, filters=vnat_filter)
        # Return exist vnat for fixed ip and fixed port.
        if vnats:
            return self._make_vnat_dict(vnats[0])
        with context.session.begin(subtransactions=True):
            args = dict(id=vn_id,
                        tenant_id=tenant_id,
                        vserver_id=vserver_id,
                        device_id=vn['device_id'],
                        port_id=port_id,
                        external_ip_address=external_ip_address,
                        external_port=external_port,
                        fixed_ip_address=vn['fixed_ip_address'],
                        fixed_port=fixed_port,
                        admin_state_up=vn['admin_state_up'],
                        vnat_type=vn['vnat_type'],
                        shared=shared,
                        status=status)
            vnat_db = VNAT(**args)
            context.session.add(vnat_db)
        vnat = self._make_vnat_dict(vnat_db)
        if (vnat.get('fixed_ip_address', None) and
            vnat.get('fixed_port', None)):
            nat_rpc_agent_api.NatAgentNotify.vnat_created(context, vnat)
        return vnat

    def update_vnat(self, context, id, vnat):
        vn = vnat['vnat']
        with context.session.begin(subtransactions=True):
            vnat_db = self._get_vnat(context, id)
            # Ensure we actually have something to update
            if vn.keys():
                vnat_db.update(vn)
        return self._make_vnat_dict(vnat_db)

    def delete_vnat(self, context, id):
        vnat_db = self._get_vnat(context, id)
        vnat = self._make_vnat_dict(vnat_db)
        agents = self.list_nat_agents_hosting_vnat(context, id)
        for agent in agents['agents']:
            self.remove_vnat_from_nat_agent(context, agent['id'], id)
            if vnat.get('vserver_id', None):
                nat_rpc_agent_api.NatAgentNotify.vnat_deleted(context, vnat,
                                                              agent['host'])
        if vnat.get('vserver_id', None):
            vserver = {'vserver': {'admin_state_up': False}}
            self.update_vserver(context, vnat['vserver_id'], vserver)
        with context.session.begin(subtransactions=True):
            context.session.delete(vnat_db)

    def add_nat_interface(self, context, interface_info):
        subnet_id = interface_info['subnet_id']
        device_id = interface_info['device_id']
        use_gateway = interface_info['use_gateway']
        subnet = self._get_subnet(context, subnet_id)
        # Ensure the subnet has a gateway
        if use_gateway and not subnet['gateway_ip']:
            msg = _('Subnet for router interface must have a gateway IP')
            raise q_exc.BadRequest(resource='router', msg=msg)
        fixed_ips = attributes.ATTR_NOT_SPECIFIED
        if use_gateway:
            fixed_ips = [{'ip_address': subnet['gateway_ip'],
                          'subnet_id': subnet['id']}]
        port = self.create_port(context, {'port':
                                {'tenant_id': subnet['tenant_id'],
                                'network_id': subnet['network_id'],
                                'fixed_ips': fixed_ips,
                                'mac_address': attributes.ATTR_NOT_SPECIFIED,
                                'admin_state_up': True,
                                'device_id': device_id,
                                'device_owner': DEVICE_OWNER_NAT_INTF,
                                'name': ''}})
        return port
