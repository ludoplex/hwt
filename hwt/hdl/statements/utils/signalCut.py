from typing import List

from hwt.doc_markers import internal
from hwt.hdl.statements.utils.listOfHdlStatements import ListOfHdlStatement
from hwt.synthesizer.rtlLevel.mainBases import RtlSignalBase


@internal
def HdlStatement_cut_off_drivers_of_list(sig: RtlSignalBase,
                             statements: ListOfHdlStatement,
                             keep_mask: List[bool],
                             new_statements: ListOfHdlStatement) -> bool:
    """
    Cut all logic from statements which drives signal sig.

    :param sig: signal which drivers should be removed
    :param statements: list of statements to filter
    :param keep_mask: list of flags if True statements was driver only of sig
    :param new_statements: output list of filtered statements

    :return: True if all input statements were reduced
    """
    all_cut_off = True
    for stm in statements:
        keep = True
        if sig in stm._outputs:
            newStm = stm._cut_off_drivers_of(sig)
            if newStm is None:
                # statement is des not have drivers of sig
                all_cut_off = False
            elif newStm is stm:
                # statement drives only sig
                keep = False
                new_statements.append(newStm)
            else:
                # statement was splited on multiple statements
                all_cut_off = False
                new_statements.append(newStm)
        else:
            all_cut_off = False
        keep_mask.append(keep)

    return all_cut_off
