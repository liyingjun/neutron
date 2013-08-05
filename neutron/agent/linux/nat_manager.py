# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 KylinOS.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
#
# @author: Liyingjun KylinOS, Inc.
# based on
#   https://github.com/openstack/nova/blob/master/nova/network/linux_net.py

"""Implements nat rules using linux utilities."""

import logging

from neutron.agent.linux import iptables_manager
from neutron.agent.linux import utils

LOG = logging.getLogger(__name__)


class BaseNatManager(object):
    """Base nat manager.
    """
    def __init__(self, _execute=None, root_helper=None, use_ipv6=False):
        if _execute:
            self.execute = _execute
        else:
            self.execute = utils.execute

        self.use_ipv6 = use_ipv6
        self.root_helper = root_helper
        self.rules = list()


class LvsNatManager(BaseNatManager):
    """Wrapper for lvs nat.
    """
    def __init__(self, _execute=None, root_helper=None, use_ipv6=False):
        super(LvsNatManager, self).__init__(_execute=_execute,
                                            root_helper=root_helper,
                                            use_ipv6=use_ipv6)

    def clear_all_rules(self):
        """Clear all rules"""
        self.rules.append('-C')

    def add_nat_rule(self, ext_ip, ext_port, fixed_ip, fixed_port, gateway):
        """Add the nat rule with options"""
        self.rules.append('-A -t %s:%s -s rr' % (ext_ip, ext_port))
        self.rules.append('-a -t %s:%s -r %s:%s -m' % (ext_ip, ext_port,
                                                       fixed_ip, fixed_port))

    def delete_nat_rule(self, ext_ip, ext_port, fixed_ip, fixed_port):
        """Delete the nat rule with options"""
        self.rules.append('-d -t %s:%s -r %s:%s' % (ext_ip, ext_port,
                                                    fixed_ip, fixed_port))
        self.rules.append('-D -t %s:%s' % (ext_ip, ext_port))

    def add_user_rule(self, rule):
        """Add user defined rule"""
        self.rules.append(rule)

    def apply(self):
        s = ['ipvsadm']
        for rule in self.rules:
            args = s + rule.split(' ')
            try:
                self.execute(args, root_helper=self.root_helper)
                LOG.debug("Success to apply rule: %s", rule)
            except Exception, e:
                LOG.warn("Failed to apply rule: %s, Error: %s", rule, e)
        self.rules = list()


class IptablesNatManager(BaseNatManager):
    """Wrapper for iptables nat.
    """
    def __init__(self, _execute=None, root_helper=None, use_ipv6=False):
        super(IptablesNatManager, self).__init__(_execute=_execute,
                                                 root_helper=root_helper,
                                                 use_ipv6=use_ipv6)
        self.iptables_manager = iptables_manager.IptablesManager(
                root_helper=root_helper)

    def clear_all_rules(self):
        pass

    def _nat_rules(self, ext_ip, ext_port, fixed_ip, fixed_port, gateway):
        rules = []
        rules.append(('PREROUTING', '-d %s -p tcp -m tcp --dport %s -j '
                      'DNAT --to-destination %s:%s' % (ext_ip, ext_port,
                                                       fixed_ip, fixed_port)))
        rules.append(('POSTROUTING', '-d %s -p tcp -m tcp --dport %s -j '
                      'SNAT --to-source %s' % (fixed_ip, fixed_port, gateway)))
        return rules

    def add_nat_rule(self, ext_ip, ext_port, fixed_ip, fixed_port, gateway):
        rules = self._nat_rules(ext_ip, ext_port, fixed_ip, fixed_port,
                                gateway)
        for c, r in rules:
            self.iptables_manager.ipv4['nat'].add_rule(c, r)

    def delete_nat_rule(self, ext_ip, ext_port, fixed_ip, fixed_port, gateway):
        rules = self._nat_rules(ext_ip, ext_port, fixed_ip, fixed_port,
                                gateway)
        for c, r in rules:
            self.iptables_manager.ipv4['nat'].remove_rule(c, r)

    def add_user_rule(self, rules):
        for c, r in rules:
            self.iptables_manager.ipv4['nat'].add_rule(c, r)

    def apply(self):
        self.iptables_manager.apply()
