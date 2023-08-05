from typing import Union

from hdlConvertorAst.hdlAst import HdlValueInt
from hdlConvertorAst.hdlAst._expr import HdlValueId, HdlOp, HdlOpType
from hdlConvertorAst.translate.common.name_scope import LanguageKeyword
from hdlConvertorAst.translate.verilog_to_basic_hdl_sim_model.utils import hdl_call
from hwt.code import If
from hwt.doc_markers import internal
from hwt.hdl.operator import Operator
from hwt.hdl.operatorDefs import AllOps
from hwt.hdl.statements.assignmentContainer import HdlAssignmentContainer
from hwt.hdl.statements.utils.listOfHdlStatements import ListOfHdlStatement
from hwt.hdl.types.bits import Bits
from hwt.hdl.types.defs import BOOL, INT
from hwt.hdl.value import HValue
from hwt.serializer.hwt.ops import ToHdlAstHwt_ops
from hwt.synthesizer.rtlLevel.mainBases import RtlSignalBase
from hwt.synthesizer.rtlLevel.rtlSignal import RtlSignal
from hwt.synthesizer.rtlLevel.signalUtils.exceptions import SignalDriverErr


@internal
def isResultOfTypeConversion(sig):
    if len(sig.drivers) != 1:
        return False

    if sig.hidden:
        d = sig.singleDriver()
        return d.operator != AllOps.INDEX

    return False


class ToHdlAstVhdl2008_ops():
    op_transl_dict = {
        **ToHdlAstHwt_ops.op_transl_dict,
        AllOps.RISING_EDGE: HdlOpType.RISING,
        AllOps.FALLING_EDGE: HdlOpType.FALLING,
    }
    _cast_ops = {
        AllOps.BitsAsSigned: "SIGNED",
        AllOps.BitsAsUnsigned: "UNSIGNED",
        AllOps.BitsAsVec: "STD_LOGIC_VECTOR",
    }

    @internal
    def _tmp_var_for_ternary(self, val: RtlSignal):
        """
        Optionally convert boolean to std_logic_vector
        """
        isNew, o = self.tmpVars.create_var_cached(
            "tmpTernary_",
            val._dtype,
            postponed_init=True,
            extra_args=(val, bool, 1, 0))
        if isNew:
            cond, ifTrue, ifFalse = val.drivers[0].operands
            if_ = If(cond)
            if_.ifTrue.append(HdlAssignmentContainer(ifTrue, o,
                                         virtual_only=True,
                                         parentStm=if_))
            if_.ifFalse = ListOfHdlStatement()
            if_.ifFalse.append(HdlAssignmentContainer(ifFalse, o,
                                          virtual_only=True,
                                          parentStm=if_))
            if_._outputs.append(o)
            for obj in (cond, ifTrue, ifFalse):
                if isinstance(obj, RtlSignalBase):
                    if_._inputs.append(obj)
            o.drivers.append(if_)
            if_._discover_enclosure()
            self.tmpVars.finish_var_init(o)

        return o

    def _as_Bits(self, val: Union[RtlSignal, HValue]):
        if val._dtype == BOOL:
            bit1_t = Bits(1)
            isNew, o = self.tmpVars.create_var_cached(
                "tmpBool2std_logic_",
                bit1_t,
                postponed_init=True,
                extra_args=(val, int, 1, 0))
            if isNew:
                ifTrue, ifFalse = bit1_t.from_py(1), bit1_t.from_py(0)
                if_ = If(val)
                if_.ifTrue.append(HdlAssignmentContainer(ifTrue, o, virtual_only=True, parentStm=if_))
                if_.ifFalse = []
                if_.ifFalse.append(HdlAssignmentContainer(ifFalse, o, virtual_only=True, parentStm=if_))
                if_._outputs.append(o)
                o.drivers.append(if_)
                self.tmpVars.finish_var_init(o)
            return o
        else:
            assert isinstance(val._dtype, Bits), val._dtype
            return val

    def _as_Bits_vec(self, val: Union[RtlSignal, HValue]):
        val = self._as_Bits(val)
        t = val._dtype
        if t.force_vector or t.bit_length() != 1:
            # already a std_logic_vector
            return val
        # std_logic -> std_logic_vector
        std_logic_vector = Bits(1, signed=t.signed, force_vector=True)
        isNew, o = self.tmpVars.create_var_cached(
            "tmp_std_logic2vector_",
            std_logic_vector,
            postponed_init=True,
            extra_args=(val, std_logic_vector))
        if isNew:
            o.drivers.append(HdlAssignmentContainer(val, o, virtual_only=True))
            self.tmpVars.finish_var_init(o)
        return o

    def as_hdl_operand(self, operand: Union[RtlSignal, HValue]):
        # no nested ternary in expressions like
        # ( '1'  WHEN r = f ELSE  '0' ) & "0"
        # extract them as a tmp variable
        try:
            isTernaryOp = operand.hidden\
                and operand.drivers[0].operator == AllOps.TERNARY
        except (AttributeError, IndexError):
            isTernaryOp = False

        if isTernaryOp:
            # rewrite ternary operator as if
            operand = self._tmp_var_for_ternary(operand)
        return self.as_hdl(operand)

    def apply_cast(self, t_name, op):
        return hdl_call(HdlValueId(t_name, obj=LanguageKeyword()),
                        [op, ])

    def _wrapConcatInTmpVariable(self, op):
        if isinstance(op, RtlSignalBase) and op.hidden:
            # if left operand is concatenation and this is not concatenation we must extract it as tmp variable
            # because VHDL would not be able to resolve type of concatenated signal otherwise
            try:
                d = op.singleDriver()
            except SignalDriverErr:
                d = None

            if d is not None and isinstance(d, Operator) and d.operator is AllOps.CONCAT:
                _, op = self.tmpVars.create_var_cached("tmpConcatExpr_", op._dtype, def_val=op)
        return op

    def as_hdl_Operator(self, op: Operator):
        ops = op.operands
        o = op.operator

        if o == AllOps.INDEX:
            op0, op1 = ops
            if isinstance(op0, RtlSignalBase) and isResultOfTypeConversion(op0):
                _, op0 = self.tmpVars.create_var_cached("tmpTypeConv_", op0._dtype, def_val=op0)
            if isinstance(op1, RtlSignalBase) and isResultOfTypeConversion(op1):
                _, op1 = self.tmpVars.create_var_cached("tmpIndexTypeConv_", op1._dtype, def_val=op1)

            # if the op0 is not signal or other index index operator it is extracted
            # as tmp variable
            op0 = self.as_hdl_operand(op0)
            op0_t = ops[0]._dtype
            if isinstance(op0_t, Bits) and op0_t.bit_length() == 1 and not op0_t.force_vector:
                assert int(ops[1]) == 0, ops
                # drop whole index operator because it is useless
                return op0

            if isinstance(op1._dtype, Bits) and op1._dtype != INT:
                if op1._dtype.signed is None:
                    if op1._dtype.bit_length() == 1 and not op1._dtype.force_vector:
                        _, op1 = self.tmpVars.create_var_cached("tmp1bToUnsigned_", Bits(1, force_vector=True), def_val=op1)
                    _op1 = self.as_hdl_operand(op1)
                    _op1 = self.apply_cast("UNSIGNED", _op1)
                else:
                    _op1 = self.as_hdl_operand(op1)

                _op1 = self.apply_cast("TO_INTEGER", _op1)
            else:
                _op1 = self.as_hdl_operand(op1)

            return HdlOp(HdlOpType.INDEX, [op0, _op1])

        elif o == AllOps.TERNARY:
            _c, _op0, _op1 = ops
            op0 = self.as_hdl_cond(_c, True)
            op1 = self.as_hdl_operand(_op0)
            t0 = _op0._dtype
            t1 = _op1._dtype
            if t0 != t1:
                assert isinstance(t0, Bits) and\
                           isinstance(t1, Bits) and\
                           t0.bit_length() == t1.bit_length() and\
                           bool(t0.signed) == bool(t1.signed), (t0, t1)
                _, _op1 = self.tmpVars.create_var_cached("tmpTernaryAutoCast_", t0, def_val=_op1)

            op2 = self.as_hdl_operand(_op1)
            return HdlOp(HdlOpType.TERNARY, [op0, op1, op2])
        else:
            _o = self._cast_ops.get(o, None)
            if _o is not None:
                op0 = ops[0]
                op0 = self._as_Bits_vec(op0)
                if isinstance(op0, RtlSignalBase) and op0.hidden:
                    _, op0 = self.tmpVars.create_var_cached("tmpCastExpr_", op0._dtype, def_val=op0)
                return self.apply_cast(_o, self.as_hdl_operand(op0))

            o = self.op_transl_dict[o]
            if len(ops) == 2:
                res_t = op.result._dtype
                op0, op1 = ops

                if o != HdlOpType.CONCAT:
                    op0 = self._wrapConcatInTmpVariable(op0)
                    op1 = self._wrapConcatInTmpVariable(op1)

                if isinstance(res_t, Bits) and res_t != BOOL:
                    op0 = self._as_Bits(op0)
                    op1 = self._as_Bits(op1)

                _op0 = self.as_hdl_operand(op0)
                _op1 = self.as_hdl_operand(op1)
                if o == HdlOpType.EQ and isinstance(_op0, HdlValueId) and\
                            (isinstance(_op0.obj._dtype, Bits) and self._expandBitsOperandType(_op0.obj) == BOOL) and\
                            isinstance(_op1, HdlValueInt) and\
                            _op1.val:
                    # drop unnecessary casts
                    return _op0
                else:
                    return HdlOp(o, [_op0, _op1])

            return HdlOp(o, [self.as_hdl_operand(o2)
                             for o2 in ops])
