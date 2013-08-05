# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack Foundation.
# All Rights Reserved.
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
# @author: Yingjun Li, KylinOS, Inc.

import random

from sqlalchemy.orm import exc
from sqlalchemy.sql import exists

from neutron.common import constants
from neutron.db import nat_db
from neutron.db import agents_db
from neutron.db import agentschedulers_db
from neutron.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class ChanceScheduler(object):
    """Allocate a NAT agent for a vnat in a random way.
    More sophisticated scheduler (similar to filter scheduler in nova?)
    can be introduced later."""

    def schedule(self, plugin, context, network_id=None):
        """Schedule default vnat to a NAT agent while a port created"""
        with context.session.begin(subtransactions=True):
            query = context.session.query(agents_db.Agent)
            query = query.filter(agents_db.Agent.agent_type ==
                                 constants.AGENT_TYPE_NAT,
                                 agents_db.Agent.admin_state_up == True)
            try:
                agents = query.all()
            except exc.NoResultFound:
                LOG.warn(_('No enabled NAT agent on host %s'))
                return False
            if network_id:
                # Select nat agent hosting the gateway of the network
                filters = dict(network_id=[network_id],
                               device_owner=[constants.DEVICE_OWNER_NAT_INTF])
                nat_intfs = plugin.get_ports(context, filters=filters)
                agent_ids = [port['device_id'] for port in nat_intfs]
                if agent_ids:
                    agents = [plugin.get_agent(context, agent_ids[0])]
            active_agents = [agent for agent in agents if not
                             agents_db.AgentDbMixin.is_agent_down(
                             agent['heartbeat_timestamp'])]
            if not active_agents:
                LOG.warn(_('No active NAT agent found'))
                return False
            chosen_agent = random.choice(active_agents)
        return chosen_agent

    def auto_schedule_vnats(self, plugin, context, host):
        """Schedule non-hosted vnats to the NAT agent on
        the specified host."""
        with context.session.begin(subtransactions=True):
            query = context.session.query(agents_db.Agent)
            query = query.filter(agents_db.Agent.agent_type ==
                                 constants.AGENT_TYPE_NAT,
                                 agents_db.Agent.host == host,
                                 agents_db.Agent.admin_state_up == True)
            try:
                nat_agent = query.one()
            except (exc.MultipleResultsFound, exc.NoResultFound):
                LOG.warn(_('No enabled NAT agent on host %s'),
                         host)
                return False
            if agents_db.AgentDbMixin.is_agent_down(
                nat_agent['heartbeat_timestamp']):
                LOG.warn(_('NAT agent %s is not active'), nat_agent.id)
            vnat_stmt = ~exists().where(
                nat_db.VNAT.id ==
                agentschedulers_db.VnatNatAgentBinding.vnat_id)
            vnat_ids = context.session.query(
                nat_db.VNAT.id).filter(vnat_stmt).all()
            if not vnat_ids:
                LOG.debug(_('No non-hosted vnats'))
                return False
            for vnat_id in vnat_ids:
                binding = agentschedulers_db.VnatNatAgentBinding()
                binding.nat_agent = nat_agent
                binding.vnat_id = vnat_id[0]
                context.session.add(binding)
        return True
