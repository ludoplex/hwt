from hwt.synthesizer.interfaceLevel.getDefaultClkRts import getRst, getClk
from hwt.synthesizer.interfaceLevel.interfaceUtils.utils import NotSpecified
from hwt.synthesizer.interfaceLevel.mainBases import UnitBase
from hwtSimApi.hdlSimulator import HdlSimulator
from ipCorePackager.intfIpMeta import IntfIpMetaNotSpecified


class InterfaceceImplDependentFns():
    """
    Interface functions which have high potential to be overloaded
    in concrete interface implementation
    """

    def _getIpCoreIntfClass(self):
        raise IntfIpMetaNotSpecified()

    def _initSimAgent(self, sim: HdlSimulator):
        raise NotSpecified("Override this function in your interface"
                           " implementation to have simultion agent"
                           f" specified ({self})")

    def _getAssociatedRst(self):
        """
        If interface has associated rst(_n) return it otherwise
        try to find rst(_n) on parent recursively
        """
        a = self._associatedRst

        if a is not None:
            return a

        p = self._parent
        assert p is not None

        return getRst(p) if isinstance(p, UnitBase) else p._getAssociatedRst()

    def _getAssociatedClk(self):
        """
        If interface has associated clk return it otherwise
        try to find clk on parent recursively
        """
        a = self._associatedClk

        if a is not None:
            return a

        p = self._parent
        assert p is not None

        return getClk(p) if isinstance(p, UnitBase) else p._getAssociatedClk()

    def __copy__(self):
        """
        Create new instance of interface of same type and configuration
        """
        intf = self.__class__()
        intf._updateParamsFrom(self)
        return intf
