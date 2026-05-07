"""
技能库系统 - 技能管理、渐进式披露、自我进化
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


SKILL_INDEX_FILE = "skill_index.json"


class Skill:
    """技能定义"""
    def __init__(self, name: str, category: str, description: str, 
                 trigger_keywords: List[str], token_cost: int = 500,
                 success_count: int = 0, last_used: str = None, 
                 created_at: str = None, file_path: str = None):
        self.name = name
        self.category = category
        self.description = description
        self.trigger_keywords = trigger_keywords
        self.token_cost = token_cost
        self.success_count = success_count
        self.last_used = last_used or datetime.now().isoformat()
        self.created_at = created_at or datetime.now().isoformat()
        self.file_path = file_path
    
    def to_index_dict(self) -> Dict:
        """返回索引格式（轻量）"""
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "trigger_keywords": self.trigger_keywords,
            "token_cost": self.token_cost,
            "success_count": self.success_count,
            "last_used": self.last_used,
            "created_at": self.created_at
        }
    
    @classmethod
    def from_index_dict(cls, data: Dict, file_path: str = None):
        """从索引字典创建"""
        return cls(
            name=data['name'],
            category=data.get('category', 'uncategorized'),
            description=data.get('description', ''),
            trigger_keywords=data.get('trigger_keywords', []),
            token_cost=data.get('token_cost', 500),
            success_count=data.get('success_count', 0),
            last_used=data.get('last_used'),
            created_at=data.get('created_at'),
            file_path=file_path
        )


class SkillManager:
    """技能管理器 - 支持渐进式披露"""
    
    def __init__(self, skills_path: str):
        self.skills_path = Path(skills_path)
        self.skills_path.mkdir(parents=True, exist_ok=True)
        self._index = None
        self._cache = {}  # 完整技能缓存
    
    def _get_index_path(self) -> Path:
        return self.skills_path / SKILL_INDEX_FILE
    
    def load_index(self) -> List[Dict]:
        """加载技能索引（轻量）"""
        if self._index is not None:
            return self._index
        
        index_path = self._get_index_path()
        if not index_path.exists():
            self._index = []
            self._save_index()
            return self._index
        
        with open(index_path, 'r', encoding='utf-8') as f:
            self._index = json.load(f)
        
        return self._index
    
    def _save_index(self):
        """保存技能索引"""
        index_path = self._get_index_path()
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)
    
    def list_skills(self, brief: bool = True) -> List[Dict]:
        """列出所有技能（brief=True时只返回索引）"""
        index = self.load_index()
        if brief:
            return index  # 只返回轻量索引
        else:
            # 返回完整技能
            full_skills = []
            for skill_data in index:
                skill = self.load_skill(skill_data['name'])
                if skill:
                    full_skills.append(skill.to_index_dict())
            return full_skills
    
    def load_skill(self, name: str) -> Optional[Skill]:
        """按需加载完整技能（渐进式披露）"""
        # 检查缓存
        if name in self._cache:
            return self._cache[name]
        
        # 从索引获取基本信息
        index = self.load_index()
        skill_data = None
        for s in index:
            if s['name'] == name:
                skill_data = s
                break
        
        if not skill_data:
            return None
        
        # 加载完整技能文档
        skill_path = self.skills_path / name / "SKILL.md"
        if not skill_path.exists():
            # 技能文件不存在，返回索引数据
            return Skill.from_index_dict(skill_data)
        
        # 读取SKILL.md
        with open(skill_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析YAML frontmatter（如果有）
        import re
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
        
        skill = Skill.from_index_dict(skill_data, file_path=str(skill_path))
        
        if frontmatter_match:
            # 有frontmatter
            import yaml
            try:
                metadata = yaml.safe_load(frontmatter_match.group(1))
                skill.metadata = metadata
                skill.full_content = frontmatter_match.group(2)
            except:
                skill.full_content = content
        else:
            skill.full_content = content
        
        # 更新缓存
        self._cache[name] = skill
        return skill
    
    def register_skill(self, name: str, category: str, description: str,
                       trigger_keywords: List[str], full_content: str = None):
        """注册新技能"""
        # 检查是否已存在
        index = self.load_index()
        for i, s in enumerate(index):
            if s['name'] == name:
                # 更新现有技能
                index[i] = Skill(
                    name=name,
                    category=category,
                    description=description,
                    trigger_keywords=trigger_keywords,
                    token_cost=len(full_content) // 4 if full_content else 500,
                    success_count=s.get('success_count', 0),
                    last_used=datetime.now().isoformat(),
                    created_at=s.get('created_at', datetime.now().isoformat())
                ).to_index_dict()
                self._save_index()
                break
        else:
            # 新增技能
            new_skill = Skill(
                name=name,
                category=category,
                description=description,
                trigger_keywords=trigger_keywords,
                token_cost=len(full_content) // 4 if full_content else 500,
                created_at=datetime.now().isoformat()
            )
            index.append(new_skill.to_index_dict())
            self._save_index()
        
        # 保存完整技能文档
        if full_content:
            skill_dir = self.skills_path / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            with open(skill_dir / "SKILL.md", 'w', encoding='utf-8') as f:
                f.write(full_content)
        
        # 清除缓存
        if name in self._cache:
            del self._cache[name]
    
    def delete_skill(self, name: str) -> bool:
        """删除技能"""
        index = self.load_index()
        new_index = [s for s in index if s['name'] != name]
        
        if len(new_index) == len(index):
            return False  # 技能不存在
        
        self._index = new_index
        self._save_index()
        
        # 删除技能目录
        import shutil
        skill_dir = self.skills_path / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        
        # 清除缓存
        if name in self._cache:
            del self._cache[name]
        
        return True
    
    def recommend_skills(self, user_input: str, limit: int = 3) -> List[Skill]:
        """基于用户输入推荐技能（渐进式披露）"""
        index = self.load_index()
        scores = []
        
        for skill_data in index:
            score = 0.0
            
            # 关键词匹配
            for keyword in skill_data.get('trigger_keywords', []):
                if keyword.lower() in user_input.lower():
                    score += 1.0
            
            # 使用频率（成功率）
            success_count = skill_data.get('success_count', 0)
            score += min(success_count * 0.1, 1.0)
            
            # 时间衰减（最近使用的优先）
            last_used_str = skill_data.get('last_used')
            if last_used_str:
                try:
                    last_used = datetime.fromisoformat(last_used_str)
                    days_ago = (datetime.now() - last_used).days
                    time_score = max(0, 1.0 - days_ago * 0.05)
                    score += time_score * 0.5
                except:
                    pass
            
            if score > 0:
                scores.append((skill_data['name'], score))
        
        # 按分数排序
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # 加载推荐的技能
        recommended = []
        for skill_name, score in scores[:limit]:
            skill = self.load_skill(skill_name)
            if skill:
                recommended.append(skill)
        
        return recommended
    
    def update_skill_usage(self, name: str, success: bool = True):
        """更新技能使用统计"""
        index = self.load_index()
        
        for i, s in enumerate(index):
            if s['name'] == name:
                index[i]['last_used'] = datetime.now().isoformat()
                if success:
                    index[i]['success_count'] = index[i].get('success_count', 0) + 1
                self._save_index()
                break
    
    def generate_skill_from_experience(self, task_description: str, 
                                        execution_steps: str, 
                                        tool_calls: List[Dict]) -> Optional[Dict]:
        """从任务执行经验生成技能（自我进化）"""
        # 这个方法会调用LLM来生成技能文档
        # 返回技能数据字典，供LLM调用后使用
        return {
            'task': task_description,
            'steps': execution_steps,
            'tools': tool_calls
        }
