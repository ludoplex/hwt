from typing import Union, List

from hwt.hdl.types.array import HArray
from hwt.hdl.types.bits import Bits
from hwt.hdl.types.hdlType import HdlType
from hwt.hdl.types.stream import HStream
from hwt.hdl.types.struct import HStruct
from hwt.hdl.types.typeCast import toHVal
from hwt.hdl.types.union import HUnion
from hwt.hdl.value import HValue
from hwt.synthesizer.rtlLevel.mainBases import RtlSignalBase


def walkFlattenFields(sigOrVal: Union[RtlSignalBase, HValue], skipPadding=True):
    """
    Walk all simple values in HStruct or HArray
    """
    t = sigOrVal._dtype
    if isinstance(t, Bits):
        yield sigOrVal
    elif isinstance(t, HUnion):
        yield from walkFlattenFields(sigOrVal._val, skipPadding=skipPadding)
    elif isinstance(t, HStruct):
        for f in t.fields:
            isPadding = f.name is None
            if not isPadding or not skipPadding:
                v = f.dtype.from_py(None) if isPadding else getattr(sigOrVal, f.name)
                yield from walkFlattenFields(v)

    elif isinstance(t, HArray):
        for item in sigOrVal:
            yield from walkFlattenFields(item)
    elif isinstance(t, HStream):
        assert isinstance(sigOrVal, HValue), sigOrVal
        for v in sigOrVal:
            yield from walkFlattenFields(v)
    else:
        raise NotImplementedError(t)


def HValue_from_words(t: HdlType,
                    data: List[Union[HValue, RtlSignalBase, int]],
                    getDataFn=None, dataWidth=None) -> HValue:
    """
    Parse raw Bits array to a value of specified HdlType
    """
    if getDataFn is None:
        assert dataWidth is not None

        def _getDataFn(x):
            return toHVal(x)._auto_cast(Bits(dataWidth))

        getDataFn = _getDataFn

    val = t.from_py(None)

    fData = iter(data)

    # actual is storage variable for items from frameData
    actualOffset = 0
    actual = None

    for v in walkFlattenFields(val, skipPadding=False):
        # walk flatten fields and take values from fData and parse them to
        # field
        required = v._dtype.bit_length()

        if actual is None:
            actualOffset = 0
            try:
                actual = getDataFn(next(fData))
            except StopIteration:
                raise ValueError("Insufficcient amount of data to build value for specified type", t, v, required)

            if dataWidth is None:
                dataWidth = actual._dtype.bit_length()
            actuallyHave = dataWidth
        else:
            actuallyHave = actual._dtype.bit_length() - actualOffset

        while actuallyHave < required:
            # collect data for this field
            try:
                d = getDataFn(next(fData))
            except StopIteration:
                raise ValueError("Insufficcient amount of data to build value for specified type", t, v, required, actuallyHave)

            actual = d._concat(actual)
            actuallyHave += dataWidth

        if actuallyHave >= required:
            # parse value of actual to field
            # skip padding
            _v = actual[(required + actualOffset):actualOffset]
            _v = _v._auto_cast(v._dtype)
            v.val = _v.val
            v.vld_mask = _v.vld_mask

            # update slice out what was taken
            actuallyHave -= required
            actualOffset += required

        if actuallyHave == 0:
            actual = None

    if actual is not None:
        assert actual._dtype.bit_length(
        ) - actualOffset < dataWidth, (
            "It should be just a padding at the end of frame, but there is some additional data"
        )
    return val


def is_only_padding(t: HdlType) -> bool:
    if isinstance(t, HStruct):
        return not any(
            f.name is not None and not is_only_padding(f.dtype)
            for f in t.fields
        )
    elif isinstance(t, (HArray, HStream)):
        return is_only_padding(t.element_t)
    return False
