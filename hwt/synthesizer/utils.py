# -*- coding: utf-8 -*-

from io import StringIO

from hwt.constraints import _get_absolute_path
from hwt.serializer.serializer_config import DummySerializerConfig
from hwt.serializer.serializer_filter import SerializerFilterDoNotExclude
from hwt.serializer.store_manager import SaveToStream, StoreManager
from hwt.serializer.vhdl import Vhdl2008Serializer
from hwt.synthesizer.componentPath import ComponentPath
from hwt.synthesizer.dummyPlatform import DummyPlatform
from hwt.synthesizer.unit import Unit, HdlConstraintList


def to_rtl(unit_or_cls: Unit, store_manager: StoreManager,
           name: str=None,
           target_platform=DummyPlatform()):
    """
    Convert unit to RTL using specified serializer

    :param unitOrCls: unit instance or class, which should be converted
    :param name: name override of top unit (if is None name is derived
        form class name)
    :param target_platform: meta-informations about target platform, distributed
        on every unit under _target_platform attribute
        before Unit._impl() is called
    """
    u = unit_or_cls if isinstance(unit_or_cls, Unit) else unit_or_cls()
    u._target_platform = target_platform
    u._store_manager = store_manager
    u._loadDeclarations()
    if name is not None:
        assert isinstance(name, str)
        u._hdl_module_name = u._name = name

    # serialize all unit instances to HDL code
    constraints = HdlConstraintList()
    for _, obj in u._to_rtl(target_platform, store_manager):
        obj: Unit
        # collect constraints directly in current component
        constraints.extend(obj._constraints)

        if obj._shared_component_with:
            # if the instance is shared with something else make
            # the paths in constraints relative to a component
            assert obj._shared_component_with[0]._shared_component_with is None
            path_old = _get_absolute_path(obj._shared_component_with[0])
            path_new = _get_absolute_path(obj)
            for c in _Unit_constraints_copy_recursively(
                    obj, path_old, path_new):
                constraints.append(c)

    if constraints:
        # serialize all constraints in design
        store_manager.write(constraints)

    return store_manager


def _Unit_constraints_copy_recursively(u: Unit, path_orig: ComponentPath, path_new: ComponentPath):
    if u._shared_component_with:
        assert not u._constraints
        assert not u._units
        orig_u, _, _ = u._shared_component_with
        _path_orig = _get_absolute_path(orig_u)
        yield from _Unit_constraints_copy_recursively(
            orig_u, _path_orig, path_new)
    else:
        for c in u._constraints:
            yield c._copy_with_root_upadate(path_orig, path_new)

        for su in u._units:
            yield from _Unit_constraints_copy_recursively(
                su, ComponentPath(*path_orig, su), ComponentPath(*path_new, su))


def to_rtl_str(unit_or_cls: Unit,
               serializer_cls=Vhdl2008Serializer, name: str=None,
               target_platform=DummyPlatform()):
    """
    Generate HDL string and return it
    """
    buff = StringIO()
    store_manager = SaveToStream(serializer_cls, buff)
    to_rtl(unit_or_cls, store_manager, name, target_platform)
    return buff.getvalue()


def serializeAsIpcore(unit, folderName=".", name=None,
                      serializer_cls=Vhdl2008Serializer,
                      target_platform=DummyPlatform()):
    """
    Create an IPCore package
    """
    from hwt.serializer.ip_packager import IpPackager
    p = IpPackager(unit, name=name,
                   serializer_cls=serializer_cls,
                   target_platform=target_platform)
    p.createPackage(folderName)
    return p


def synthesised(u: Unit, target_platform=DummyPlatform()):
    """
    Elaborate design without producing any HDL
    """
    sm = StoreManager(DummySerializerConfig,
                      _filter=SerializerFilterDoNotExclude())
    if not hasattr(u, "_interfaces"):
        u._loadDeclarations()

    for _ in u._to_rtl(target_platform, sm):
        pass
    return u
