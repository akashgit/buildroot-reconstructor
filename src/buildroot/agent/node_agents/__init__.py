"""Node-scoped Claude Code reviewer agents for each pipeline step."""

from buildroot.agent.node_agents.base import EVIDENCE_HIERARCHY, Candidate, NodeAgent
from buildroot.agent.node_agents.pom_agent import PomAgent
from buildroot.agent.node_agents.parent_chain_agent import ParentChainAgent
from buildroot.agent.node_agents.property_agent import PropertyAgent
from buildroot.agent.node_agents.repo_agent import RepoAgent
from buildroot.agent.node_agents.ci_agent import CIAgent
from buildroot.agent.node_agents.jdk_agent import JdkAgent
from buildroot.agent.node_agents.image_agent import ImageAgent
from buildroot.agent.node_agents.tag_agent import TagAgent
from buildroot.agent.node_agents.build_cmd_agent import BuildCmdAgent
from buildroot.agent.node_agents.template_agent import TemplateAgent

ALL_NODE_AGENTS = [
    PomAgent,
    ParentChainAgent,
    PropertyAgent,
    RepoAgent,
    CIAgent,
    JdkAgent,
    ImageAgent,
    TagAgent,
    BuildCmdAgent,
    TemplateAgent,
]

__all__ = [
    "EVIDENCE_HIERARCHY",
    "Candidate",
    "NodeAgent",
    "PomAgent",
    "ParentChainAgent",
    "PropertyAgent",
    "RepoAgent",
    "CIAgent",
    "JdkAgent",
    "ImageAgent",
    "TagAgent",
    "BuildCmdAgent",
    "TemplateAgent",
    "ALL_NODE_AGENTS",
]
