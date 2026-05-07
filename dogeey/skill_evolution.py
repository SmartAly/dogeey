"""
Skill Evolution System - 技能组合进化
技能会"生孩子"：组合两个技能生成新技能
支持进化、变异、选择
"""

import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class SkillGene:
    """技能基因 - 定义技能的核心特征"""
    name: str
    category: str  # code, data, web, system, creative, etc.
    tools_required: List[str]  # 需要的工具
    complexity: float  # 复杂度 (0.0-1.0)
    success_rate: float  # 历史成功率
    avg_duration: float  # 平均执行时间（秒）
    tags: List[str]  # 标签（用于匹配和组合）
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "category": self.category,
            "tools_required": self.tools_required,
            "complexity": self.complexity,
            "success_rate": self.success_rate,
            "avg_duration": self.avg_duration,
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SkillGene':
        return cls(
            name=data["name"],
            category=data.get("category", "unknown"),
            tools_required=data.get("tools_required", []),
            complexity=data.get("complexity", 0.5),
            success_rate=data.get("success_rate", 0.5),
            avg_duration=data.get("avg_duration", 60.0),
            tags=data.get("tags", [])
        )


@dataclass
class ExperienceObject:
    """经验对象 - 跨会话经验库的核心"""
    id: Optional[str] = None
    task_type: str = "unknown"
    task_description: str = ""
    skill_used: str = ""
    success: bool = False
    duration: float = 0.0
    score: float = 0.0  # 元认知评分
    lessons_learned: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    related_skills: List[str] = field(default_factory=list)  # 可组合技能
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.id is None:
            import uuid
            self.id = str(uuid.uuid4())[:8]
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "task_description": self.task_description,
            "skill_used": self.skill_used,
            "success": self.success,
            "duration": self.duration,
            "score": self.score,
            "lessons_learned": self.lessons_learned,
            "improvement_suggestions": self.improvement_suggestions,
            "related_skills": self.related_skills,
            "timestamp": self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ExperienceObject':
        return cls(
            id=data.get("id"),
            task_type=data.get("task_type", "unknown"),
            task_description=data.get("task_description", ""),
            skill_used=data.get("skill_used", ""),
            success=data.get("success", False),
            duration=data.get("duration", 0.0),
            score=data.get("score", 0.0),
            lessons_learned=data.get("lessons_learned", []),
            improvement_suggestions=data.get("improvement_suggestions", []),
            related_skills=data.get("related_skills", []),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now()
        )


class SkillEvolutionSystem:
    """技能进化系统 - 管理技能组合、变异、选择"""
    
    def __init__(self, skills_dir: str = None, experience_db: str = None):
        if skills_dir is None:
            skills_dir = Path.home() / ".dogeey" / "skills"
        if experience_db is None:
            experience_db = Path.home() / ".dogeey" / "experience.db"
        
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.experience_db = Path(experience_db)
        
        # 技能基因库
        self.gene_library: Dict[str, SkillGene] = {}
        # 经验库
        self.experiences: List[ExperienceObject] = []
        
        self._load_gene_library()
        self._load_experiences()
    
    def _load_gene_library(self):
        """加载技能基因库"""
        gene_file = self.skills_dir.parent / "gene_library.json"
        if gene_file.exists():
            try:
                with open(gene_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for item in data:
                    gene = SkillGene.from_dict(item)
                    self.gene_library[gene.name] = gene
            except Exception as e:
                print(f"⚠️ 加载基因库失败: {e}")
    
    def _save_gene_library(self):
        """保存技能基因库"""
        gene_file = self.skills_dir.parent / "gene_library.json"
        try:
            data = [gene.to_dict() for gene in self.gene_library.values()]
            with open(gene_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ 保存基因库失败: {e}")
    
    def _load_experiences(self):
        """加载跨会话经验"""
        if self.experience_db.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(self.experience_db)
                cursor = conn.execute("""
                    SELECT id, task_type, task_description, skill_used,
                           success, duration, score, lessons_learned,
                           improvement_suggestions, related_skills, timestamp
                    FROM experiences
                    ORDER BY timestamp DESC
                    LIMIT 1000
                """)
                
                for row in cursor.fetchall():
                    exp = ExperienceObject(
                        id=row[0],
                        task_type=row[1],
                        task_description=row[2],
                        skill_used=row[3],
                        success=bool(row[4]),
                        duration=row[5],
                        score=row[6],
                        lessons_learned=json.loads(row[7]) if row[7] else [],
                        improvement_suggestions=json.loads(row[8]) if row[8] else [],
                        related_skills=json.loads(row[9]) if row[9] else [],
                        timestamp=datetime.fromisoformat(row[10]) if row[10] else datetime.now()
                    )
                    self.experiences.append(exp)
                
                conn.close()
            except Exception as e:
                print(f"⚠️ 加载经验库失败: {e}")
    
    def _init_experience_db(self):
        """初始化经验数据库"""
        try:
            import sqlite3
            conn = sqlite3.connect(self.experience_db)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiences (
                    id TEXT PRIMARY KEY,
                    task_type TEXT,
                    task_description TEXT,
                    skill_used TEXT,
                    success BOOLEAN,
                    duration REAL,
                    score REAL,
                    lessons_learned TEXT,
                    improvement_suggestions TEXT,
                    related_skills TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 初始化经验数据库失败: {e}")
    
    def register_skill(self, skill_name: str, category: str, 
                       tools_required: List[str], tags: List[str] = None) -> SkillGene:
        """注册技能到基因库"""
        gene = SkillGene(
            name=skill_name,
            category=category,
            tools_required=tools_required,
            complexity=0.5,
            success_rate=0.5,
            avg_duration=60.0,
            tags=tags or []
        )
        self.gene_library[skill_name] = gene
        self._save_gene_library()
        return gene
    
    def combine_skills(self, skill1_name: str, skill2_name: str) -> Optional[Dict]:
        """组合两个技能，生成新技能（生孩子）"""
        if skill1_name not in self.gene_library or skill2_name not in self.gene_library:
            print(f"❌ 技能不存在: {skill1_name} 或 {skill2_name}")
            return None
        
        gene1 = self.gene_library[skill1_name]
        gene2 = self.gene_library[skill2_name]
        
        # 生成新技能名称
        new_name = f"{gene1.name}_{gene2.name}_combo"
        
        # 检查是否已存在
        if new_name in self.gene_library:
            print(f"⚠️ 组合技能已存在: {new_name}")
            return None
        
        # 组合特征
        new_category = f"{gene1.category}+{gene2.category}"
        new_tools = list(set(gene1.tools_required + gene2.tools_required))
        new_complexity = min(1.0, (gene1.complexity + gene2.complexity) * 0.8)  # 组合后可能更简单
        new_tags = list(set(gene1.tags + gene2.tags))
        
        # 创建新基因
        new_gene = SkillGene(
            name=new_name,
            category=new_category,
            tools_required=new_tools,
            complexity=new_complexity,
            success_rate=0.3,  # 新技能初始成功率较低
            avg_duration=(gene1.avg_duration + gene2.avg_duration) / 2,
            tags=new_tags + ["combo", "evolved"]
        )
        
        # 创建技能文件
        skill_content = self._generate_combo_skill_content(gene1, gene2, new_gene)
        
        try:
            skill_path = self.skills_dir / f"{new_name}.md"
            with open(skill_path, 'w', encoding='utf-8') as f:
                f.write(skill_content)
            
            # 注册到基因库
            self.gene_library[new_name] = new_gene
            self._save_gene_library()
            
            print(f"🧬 技能组合成功: {new_name}")
            print(f"   类别: {new_category}")
            print(f"   工具: {', '.join(new_tools)}")
            print(f"   复杂度: {new_complexity:.2f}")
            
            return new_gene.to_dict()
        except Exception as e:
            print(f"❌ 创建组合技能失败: {e}")
            return None
    
    def _generate_combo_skill_content(self, gene1: SkillGene, gene2: SkillGene, 
                                    new_gene: SkillGene) -> str:
        """生成组合技能的SKILL.md内容"""
        content = f"""---
name: {new_gene.name}
description: 组合技能 - {gene1.name} + {gene2.name}
category: {new_gene.category}
tools: {', '.join(new_gene.tools_required)}
complexity: {new_gene.complexity}
generated: {datetime.now().isoformat()}
parent_skills: {gene1.name}, {gene2.name}
---

# {new_gene.name}

## 组合技能

此技能由 **{gene1.name}** 和 **{gene2.name}** 组合进化而来。

## 适用场景

- {gene1.category} 相关任务
- {gene2.category} 相关任务
- 需要同时利用两个技能优势的场景

## 执行步骤

### 步骤1: 分析任务
使用 {gene1.name} 的方法分析任务...

### 步骤2: 执行核心
结合 {gene2.name} 的方法执行...

### 步骤3: 验证结果
检查执行结果是否符合预期...

## 注意事项

- 此技能为自动生成的组合技能
- 初始成功率可能较低，需要多次使用进化
- 如果效果不佳，建议回退到父技能单独使用

## 进化历史

- 生成时间: {datetime.now().isoformat()}
- 父技能: {gene1.name}, {gene2.name}
- 初始复杂度: {new_gene.complexity:.2f}
"""
        return content
    
    def record_experience(self, task_type: str, task_description: str,
                         skill_used: str, success: bool,
                         duration: float, score: float,
                         lessons: List[str] = None,
                         suggestions: List[str] = None) -> str:
        """记录经验到跨会话经验库"""
        self._init_experience_db()
        
        # 找到相关技能（通过标签匹配）
        related = self._find_related_skills(task_type, skill_used)
        
        exp = ExperienceObject(
            task_type=task_type,
            task_description=task_description,
            skill_used=skill_used,
            success=success,
            duration=duration,
            score=score,
            lessons_learned=lessons or [],
            improvement_suggestions=suggestions or [],
            related_skills=related
        )
        
        # 保存到数据库
        try:
            import sqlite3
            conn = sqlite3.connect(self.experience_db)
            conn.execute("""
                INSERT OR REPLACE INTO experiences
                (id, task_type, task_description, skill_used,
                 success, duration, score, lessons_learned,
                 improvement_suggestions, related_skills, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                exp.id, exp.task_type, exp.task_description, exp.skill_used,
                exp.success, exp.duration, exp.score,
                json.dumps(exp.lessons_learned),
                json.dumps(exp.improvement_suggestions),
                json.dumps(exp.related_skills),
                exp.timestamp.isoformat()
            ))
            conn.commit()
            conn.close()
            
            # 更新技能基因的成功率
            if skill_used in self.gene_library:
                gene = self.gene_library[skill_used]
                # 简单移动平均
                old_rate = gene.success_rate
                gene.success_rate = (old_rate * 0.7 + (1.0 if success else 0.0) * 0.3)
                gene.avg_duration = (gene.avg_duration * 0.7 + duration * 0.3)
                self._save_gene_library()
            
            self.experiences.append(exp)
            print(f"📝 经验已记录: {exp.id}")
            print(f"   任务: {task_type}")
            print(f"   技能: {skill_used}")
            print(f"   成功: {success}, 评分: {score:.2f}")
            
            return exp.id
        except Exception as e:
            print(f"❌ 记录经验失败: {e}")
            return None
    
    def _find_related_skills(self, task_type: str, current_skill: str) -> List[str]:
        """找到相关技能（可用于组合）"""
        related = []
        
        for name, gene in self.gene_library.items():
            if name == current_skill:
                continue
            
            # 通过标签匹配
            if task_type in gene.tags:
                related.append(name)
            
            # 通过类别匹配
            if task_type in gene.category:
                related.append(name)
        
        return related[:5]  # 最多返回5个
    
    def get_experience_summary(self, skill_name: str = None) -> Dict:
        """获取经验总结"""
        if skill_name:
            exps = [e for e in self.experiences if e.skill_used == skill_name]
        else:
            exps = self.experiences
        
        if not exps:
            return {"message": "无经验记录"}
        
        total = len(exps)
        success_count = sum(1 for e in exps if e.success)
        avg_score = sum(e.score for e in exps) / total
        avg_duration = sum(e.duration for e in exps) / total
        
        lessons = []
        for exp in exps:
            lessons.extend(exp.lessons_learned)
        
        return {
            "total_tasks": total,
            "success_rate": success_count / total,
            "avg_score": round(avg_score, 2),
            "avg_duration": round(avg_duration, 2),
            "common_lessons": list(set(lessons))[:5]
        }
    
    def suggest_combinations(self, task_type: str) -> List[Tuple[str, str]]:
        """根据任务类型，建议技能组合（智能匹配）"""
        # 找到相关技能（多种匹配方式）
        candidates = []
        task_lower = task_type.lower()
        
        for name, gene in self.gene_library.items():
            matched = False
            
            # 1. 直接标签匹配
            if task_type in gene.tags:
                matched = True
            # 2. 技能名称包含任务类型
            elif task_lower in name.lower():
                matched = True
            # 3. 任务类型在类别中
            elif task_type in gene.category:
                matched = True
            # 4. 模糊匹配：任务类型的任何部分在标签中
            else:
                for tag in gene.tags:
                    if task_lower in tag.lower() or tag.lower() in task_lower:
                        matched = True
                        break
            
            if matched:
                candidates.append((name, gene.success_rate))
        
        # 按成功率排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # 建议前3个的两两组合
        suggestions = []
        for i in range(min(3, len(candidates))):
            for j in range(i+1, min(3, len(candidates))):
                skill1, rate1 = candidates[i]
                skill2, rate2 = candidates[j]
                avg_rate = (rate1 + rate2) / 2
                suggestions.append((f"{skill1}+{skill2}", 
                                   f"组合 {skill1} 和 {skill2} (平均成功率: {avg_rate:.1%})"))
        
        return suggestions[:5]  # 最多返回5个建议
    
    def evolve_skill(self, skill_name: str) -> Optional[Dict]:
        """进化技能（变异+选择）"""
        if skill_name not in self.gene_library:
            print(f"❌ 技能不存在: {skill_name}")
            return None
        
        gene = self.gene_library[skill_name]
        
        # 获取经验总结
        summary = self.get_experience_summary(skill_name)
        
        if summary.get("total_tasks", 0) < 5:
            print(f"⚠️ 经验不足，需要至少5次任务（当前: {summary.get('total_tasks', 0)}）")
            return None
        
        # 根据经验调整复杂度
        if summary["avg_score"] < 0.6:
            # 评分低，降低复杂度
            gene.complexity = max(0.1, gene.complexity * 0.9)
            print(f"🧬 降低复杂度: {gene.complexity:.2f}")
        elif summary["avg_score"] > 0.8:
            # 评分高，可以尝试增加复杂度
            gene.complexity = min(1.0, gene.complexity * 1.1)
            print(f"🧬 增加复杂度: {gene.complexity:.2f}")
        
        # 更新成功率
        gene.success_rate = summary["success_rate"]
        
        # 保存
        self._save_gene_library()
        
        print(f"🧬 技能 {skill_name} 已进化")
        print(f"   新成功率: {gene.success_rate:.1%}")
        print(f"   新复杂度: {gene.complexity:.2f}")
        
        return gene.to_dict()


# 导出
__all__ = ['SkillGene', 'ExperienceObject', 'SkillEvolutionSystem']
