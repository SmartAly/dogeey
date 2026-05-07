"""
狗狗 ASCII Art - Dogeey Logo
"""
DOG_LOGO = """
             .--~~,__
:-...,-------`~~'._.'
 `-,,,  ,_      ;'~U'
  _,-' ,'`-__; '--.
 (_/'~~      ''''(;

    Dogeey v1.0.0
    轻量级AI智能体
    越用越聪明
"""

DOG_SMALL = "🐕 Dogeey"

DOG_THINKING = """
    (  -_- ) 思考中...
"""

DOG_HAPPY = """
    ( ^_^ ) 完成！
"""


def get_logo():
    """返回完整Logo"""
    return DOG_LOGO


def get_small_logo():
    """返回小Logo"""
    return DOG_SMALL


def get_thinking():
    """返回思考状态"""
    return DOG_THINKING


def get_happy():
    """返回完成状态"""
    return DOG_HAPPY
