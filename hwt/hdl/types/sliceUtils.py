from hwt.doc_markers import internal
from hwt.hdl.types.defs import INT, SLICE
from hwt.hdl.types.slice import HSlice
from hwt.hdl.types.typeCast import toHVal


@internal
def slice_to_SLICE(sliceVals, width):
    """convert python slice to value of SLICE hdl type"""
    step = -1 if sliceVals.step is None else sliceVals.step
    start = sliceVals.start
    start = INT.from_py(width) if start is None else toHVal(start)
    stop = sliceVals.stop
    stop = INT.from_py(0) if stop is None else toHVal(stop)
    v = slice(start, stop, step)
    return HSlice.getValueCls()(SLICE, v, 1)
