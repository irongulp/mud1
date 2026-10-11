"""Small regression for the multidict CVE-2026-104874 reference leak."""
import gc
import sys
import unittest

from multidict import CIMultiDict


@unittest.skipUnless(hasattr(sys, 'getrefcount'), 'Requires CPython reference counting')
class DependencySecurityTests(unittest.TestCase):
    def test_items_view_set_operations_release_operand_references(self):
        operations = {
            'reflected union': lambda items, operand: operand | items,
            'subtraction': lambda items, operand: items - operand,
        }
        for name, operation in operations.items():
            with self.subTest(operation=name):
                items = CIMultiDict(seed='existing').items()
                value = object()
                operand = [('first', value), ('second', value)]
                gc.collect()
                before = sys.getrefcount(value)
                result = operation(items, operand)
                del result
                gc.collect()
                self.assertEqual(sys.getrefcount(value), before,
                                 'Items-view operation permanently retained operand values')
