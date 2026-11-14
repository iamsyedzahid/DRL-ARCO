"""Guards against the C++ scenario drifting away from the Python config."""

import re

from drl_arco.config import REPO_ROOT, load_config
from drl_arco.topology import Topology
from drl_arco.traffic import load_flows, ns3_flows_arg

SCENARIO_DIR = REPO_ROOT / "ns3" / "scratch" / "drl-arco"


def _cpp_constant(name: str) -> str:
    source = (SCENARIO_DIR / "drl-arco.cc").read_text(encoding="utf-8")
    block = re.search(rf"{name}\s*=\s*((?:\s*\"[^\"]*\")+);", source).group(1)
    return "".join(re.findall(r"\"([^\"]*)\"", block))


def test_cpp_default_links_match_config():
    assert _cpp_constant("kDefaultLinks") == Topology(load_config()["topology"]).ns3_links_arg()


def test_cpp_default_flows_match_config():
    assert _cpp_constant("kDefaultFlows") == ns3_flows_arg(load_flows(load_config()))


def test_only_one_scratch_source_looks_like_the_entry_point():
    # ns-3's scratch/CMakeLists.txt runs this regex over each .cc and takes the last match.
    pattern = re.compile(r"main[(| (]")
    matches = [p.name for p in SCENARIO_DIR.glob("*.cc")
               if pattern.search(p.read_text(encoding="utf-8"))]
    assert matches == ["drl-arco.cc"]
