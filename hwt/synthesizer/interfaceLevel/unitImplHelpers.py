from itertools import chain
from typing import Union, Optional, Tuple

from hwt.doc_markers import internal
from hwt.hdl.operatorDefs import OpDefinition
from hwt.hdl.types.array import HArray
from hwt.hdl.types.defs import BIT
from hwt.hdl.types.hdlType import HdlType
from hwt.hdl.types.struct import HStruct
from hwt.interfaces.std import Signal, Clk, Rst, Rst_n
from hwt.interfaces.structIntf import HdlType_to_Interface, StructIntf
from hwt.synthesizer.hObjList import HObjList
from hwt.synthesizer.interfaceLevel.getDefaultClkRts import getClk, getRst
from hwt.synthesizer.interfaceLevel.mainBases import UnitBase, InterfaceBase
from hwt.synthesizer.rtlLevel.constants import NOT_SPECIFIED
from hwt.synthesizer.rtlLevel.mainBases import RtlSignalBase
from hwt.synthesizer.rtlLevel.netlist import RtlNetlist
from hwt.synthesizer.rtlLevel.rtlSignal import RtlSignal
from hwt.synthesizer.rtlLevel.rtlSyncSignal import RtlSyncSignal
from ipCorePackager.constants import INTF_DIRECTION


def getSignalName(sig):
    """
    Name getter which works for RtlSignal and Interface instances as well
    """
    try:
        return sig._name
    except AttributeError:
        pass
    return sig.name


def getInterfaceName(top: "Unit", io: Union[InterfaceBase, RtlSignal,
                                            Tuple[Union[InterfaceBase, RtlSignal]]]):
    if isinstance(io, InterfaceBase):
        prefix = []
        parent = io._parent
        while parent is not None:
            if parent is top:
                break

            prefix.append(parent._name)
            parent = parent._parent
        n = io._getFullName()
        if not prefix:
            return n
        prefix.reverse()
        prefix.append(n)
        return ".".join(prefix)
    elif isinstance(io, tuple):
        return f"({', '.join(getInterfaceName(top, _io) for _io in io)})"
    else:
        return getSignalName(io)


@internal
def _default_param_updater(self, myP, otherP_val):
    myP.set_value(otherP_val)


@internal
def _normalize_default_value_dict_for_interface_array(root_val: dict,
                                                      val: Union[dict, list, None],
                                                      name_prefix: str,
                                                      hobj_list: HObjList,
                                                      neutral_value):
    """
    This function is called to convert data in format
    .. code-block:: python

        {"x": [3, 4]}
        # into
        {"x_0": 3, "x_1": 4}

    This is required because the items of HObjList are stored in _interfaces as a separate items
    and thus we can not resolve the value association otherwise.
    """

    for i, intf in enumerate(hobj_list):
        if val is neutral_value:
            continue
        elif isinstance(val, dict):
            _val = val.get(i, neutral_value)
        else:
            _val = val[i]
        if _val is neutral_value:
            continue

        elm_name = f"{name_prefix:s}_{i:d}"
        if isinstance(intf, HObjList):
            _normalize_default_value_dict_for_interface_array(root_val, _val, elm_name, intf, neutral_value)
        else:
            root_val[elm_name] = _val


@internal
def _instantiate_signals(intf: Union[Signal, HObjList, StructIntf],
                         clk: Clk, rst: Union[Rst, Rst_n], def_val, nop_val, signal_create_fn):
    intf._direction = INTF_DIRECTION.UNKNOWN
    if isinstance(intf, Signal):
        name = intf._getHdlName()
        intf._sig = signal_create_fn(
            name,
            intf._dtype,
            clk, rst, def_val, nop_val)
        intf._sig._interface = intf

    elif isinstance(intf, HObjList):
        intf_len = len(intf)
        if isinstance(def_val, dict):
            for k in def_val.keys():
                assert k > 0 and k < intf_len, ("Default value for", intf, " specifies ", k, " which is not present on interface")
        elif def_val is not None:
            assert len(def_val) == intf_len, ("Default value does not have same size, ", len(def_val), intf_len, intf)

        if isinstance(nop_val, dict):
            for k in nop_val.keys():
                assert k > 0 and k < intf_len, ("Nop value for", intf, " specifies ", k, " which is not present on interface")
        elif nop_val is not NOT_SPECIFIED:
            assert len(nop_val) == intf_len, ("Nop value does not have same size, ", len(nop_val), intf_len, intf)

        for i, elm in enumerate(intf):
            if def_val is None:
                _def_val = None
            elif isinstance(def_val, dict):
                _def_val = def_val.get(i, None)
            else:
                _def_val = def_val[i]

            if nop_val is NOT_SPECIFIED:
                _nop_val = NOT_SPECIFIED
            elif isinstance(nop_val, dict):
                _nop_val = nop_val.get(i, NOT_SPECIFIED)
            else:
                _nop_val = nop_val[i]
            _instantiate_signals(elm, clk, rst, _def_val, _nop_val, signal_create_fn)

    else:
        if def_val is not None:
            for k in tuple(def_val.keys()):
                _i = getattr(intf, k, NOT_SPECIFIED)
                assert _i is not NOT_SPECIFIED, ("Default value for", intf, " specifies ", k, " which is not present on interface")
                if isinstance(_i, HObjList):
                    _normalize_default_value_dict_for_interface_array(
                        def_val, def_val[k], k, _i, None)

        if nop_val is not NOT_SPECIFIED:
            for k in tuple(nop_val.keys()):
                _i = getattr(intf, k, NOT_SPECIFIED)
                assert _i is not NOT_SPECIFIED, ("Nop value for", intf, " specifies ", k, " which is not present on interface")
                if isinstance(_i, HObjList):
                    _normalize_default_value_dict_for_interface_array(
                        nop_val, nop_val[k],
                        k, _i, NOT_SPECIFIED)

        for elm in intf._interfaces:
            name = elm._name
            _def_val = None if def_val is None else def_val.get(name, None)
            if nop_val is NOT_SPECIFIED:
                _nop_val = NOT_SPECIFIED
            else:
                _nop_val = nop_val.get(name, NOT_SPECIFIED)

            _instantiate_signals(elm, clk, rst, _def_val, _nop_val, signal_create_fn)


@internal
def _loadDeclarations(intf_or_list: Union[HObjList, InterfaceBase], suggested_name: str):
    if isinstance(intf_or_list, HObjList):
        for i, intf in enumerate(intf_or_list):
            _loadDeclarations(intf, f"{suggested_name:s}_{i:d}")
    else:
        intf_or_list._name = suggested_name
        intf_or_list._loadDeclarations()


def Interface_without_registration(
        parent:UnitBase,
        container: Union[InterfaceBase, HObjList],
        suggested_name:str,
        def_val: Union[int, None, dict, list]=None,
        nop_val: Union[int, None, dict, list, "NOT_SPECIFIED"]=NOT_SPECIFIED):
    """
    Load all parts of interface and construct signals in RtlNetlist context with an automatic name check,
    without need to explicitly add the interface in _interfaces list.
    """
    _loadDeclarations(container, suggested_name)
    _instantiate_signals(
        container, None, None, def_val, nop_val,
        lambda name, dtype, clk, rst, def_val, nop_val: parent._sig(name, dtype,
                                                                  def_val=def_val,
                                                                  nop_val=nop_val))
    container._parent = parent
    parent._private_interfaces.append(container)
    return container


class UnitImplHelpers(UnitBase):

    def _reg(self, name: str,
             dtype: HdlType=BIT,
             def_val: Union[int, None, dict, list]=None,
             clk: Union[RtlSignalBase, None, Tuple[RtlSignalBase, OpDefinition]]=None,
             rst: Optional[RtlSignalBase]=None) -> RtlSyncSignal:
        """
        Create RTL FF register in this unit

        :param def_val: s default value of this register,
            if this value is specified reset signal of this component is used
            to generate a reset logic
        :param clk: optional clock signal specification,
            (signal or tuple(signal, edge type (AllOps.RISING_EDGE/FALLING_EDGE)))
        :param rst: optional reset signal specification
        :note: rst/rst_n resolution is done from signal type,
            if it is negated type the reset signal is interpreted as rst_n
        :note: if clk or rst is not specified default signal
            from parent unit instance will be used
        """
        if clk is None:
            clk = getClk(self)

        if def_val is None:
            # if no value is specified reset is not required
            rst = None
        elif rst is None:
            rst = getRst(self)

        if not isinstance(dtype, (HStruct, HArray)):
            # primitive data type signal
            return self._ctx.sig(
                name,
                dtype=dtype,
                clk=clk,
                syncRst=rst,
                def_val=def_val
            )
        container = HdlType_to_Interface().apply(dtype)
        _loadDeclarations(container, name)
        _instantiate_signals(
            container, clk, rst, def_val, NOT_SPECIFIED,
            lambda name, dtype, clk, rst, def_val, nop_val: self._reg(name, dtype,
                                                                      def_val=def_val,
                                                                      clk=clk, rst=rst))
        container._parent = self
        return container

    def _sig(self, name: str,
             dtype: HdlType=BIT,
             def_val: Union[int, None, dict, list]=None,
             nop_val: Union[int, None, dict, list, "NOT_SPECIFIED"]=NOT_SPECIFIED) -> RtlSignal:
        """
        Create signal in this unit

        :see: :func:`hwt.synthesizer.rtlLevel.netlist.RtlNetlist.sig`
        """
        if not isinstance(dtype, HStruct):
            # primitive data type signal
            return self._ctx.sig(name, dtype=dtype, def_val=def_val, nop_val=nop_val)
        container = HdlType_to_Interface().apply(dtype)
        return Interface_without_registration(self, container, name, def_val=def_val, nop_val=nop_val)

    @internal
    def _cleanAsSubunit(self):
        """
        Disconnect internal signals so unit can be reused by parent unit
        """
        for i in chain(self._interfaces, self._private_interfaces):
            i._clean()

    @internal
    def _signalsForSubUnitEntity(self, context: RtlNetlist, prefix: str):
        """
        generate signals in this context for all ports of this subunit
        """
        for i in self._interfaces:
            if i._isExtern:
                i._signalsForInterface(context, None, None, prefix=prefix + i._NAME_SEPARATOR)

