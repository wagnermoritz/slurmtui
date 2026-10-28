from slurmtui.slurm.parsers import hostlist


def test_expand_ranges_and_padding():
    assert hostlist.expand("htc-cmp[007-009,011],gpu820") == [
        "htc-cmp007",
        "htc-cmp008",
        "htc-cmp009",
        "htc-cmp011",
        "gpu820",
    ]


def test_expand_multiple_brackets_and_nulls():
    assert hostlist.expand("r[1-2]n[1-2]") == ["r1n1", "r1n2", "r2n1", "r2n2"]
    assert hostlist.expand("(null)") == []
    assert hostlist.expand("") == []
    assert hostlist.expand(None) == []
    assert hostlist.expand("login01") == ["login01"]


def test_expand_dedups():
    assert hostlist.expand("a1,a1,a[1-2]") == ["a1", "a2"]


def test_contract():
    assert hostlist.contract(["htc-cmp007", "htc-cmp008", "htc-cmp009", "htc-cmp011", "gpu820", "login01"]) == (
        "gpu820,htc-cmp[007-009,011],login01"
    )
    assert hostlist.contract(["htc-gpu100", "htc-gpu001", "htc-gpu002"]) == "htc-gpu[001-002,100]"
    assert hostlist.contract([]) == ""
    assert hostlist.contract(["a3", "a1", "a2"], sep=", ") == "a[1-3]"


def test_roundtrip():
    names = hostlist.expand("htc-cmp[001-003,010,023,300-313],cmp[820-859]")
    assert hostlist.expand(hostlist.contract(names)) == sorted(names)
