"""Dogeey - 轻量级AI智能体"""
from .config import config
from . import llm, core, tools, memory, profile, skills

__version__ = "1.0.0"
__all__ = ['config', 'llm', 'core', 'tools', 'memory', 'profile', 'skills']
