"""
Metacognition module - Let dogeey learn and evolve like humans
Includes: competence map, blind spot detection, self-assessment, help strategy
"""

import json
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path


class MetaCognition:
    """Metacognition module - dogeey's 'prefrontal cortex'
    
    Functions:
    1. Competence map: track what dogeey can do and how well
    2. Blind spot detection: identify knowledge gaps
    3. Self-assessment: score and reflect after each conversation
    4. Help strategy: know when to honestly say "I cannot do this"
    """
    
    def __init__(self, data_dir: str = None):
        # Data directory
        if data_dir is None:
            data_dir = os.path.expanduser("~/.dogeey")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Data files
        self.competence_file = self.data_dir / "competence_map.json"
        self.blindspots_file = self.data_dir / "blindspots.json"
        self.reflection_file = self.data_dir / "reflections.json"
        
        # Load data
        self.competence_map = self._load_json(self.competence_file, default={
            "task_types": {},
            "last_updated": None
        })
        self.blindspots = self._load_json(self.blindspots_file, default={
            "identified": [],
            "suspected": []
        })
        self.reflections = self._load_json(self.reflection_file, default={
            "recent": [],
            "patterns": {}
        })
        
        # Task type keywords mapping (English only for reliability)
        self.task_type_keywords = {
            "code_generation": ["write code", "programming", "implement", "function", "class", "code"],
            "data_analysis": ["analyze", "data", "statistics", "chart", "analysis"],
            "file_operation": ["file", "read", "write", "delete"],
            "web_search": ["search", "find", "google"],
            "conversation": ["chat", "talk", "discuss"],
            "debugging": ["debug", "bug", "error", "fix"],
            "system_operation": ["system", "command", "terminal"],
            "creative_writing": ["write", "article", "story", "create"],
            "math_calculation": ["calculate", "math", "formula"],
            "translation": ["translate", "translation"],
            "planning": ["plan", "schedule", "arrange"]
        }
    
    def _load_json(self, filepath: Path, default: dict) -> dict:
        """Load JSON data"""
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load {filepath}: {e}")
                return default
        return default
    
    def _save_json(self, filepath: Path, data: dict):
        """Save JSON data"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save {filepath}: {e}")
    
    def _classify_task(self, user_input: str) -> str:
        """Classify task type based on user input"""
        user_input_lower = user_input.lower()
        
        # Count keyword matches for each task type
        scores = {}
        for task_type, keywords in self.task_type_keywords.items():
            score = sum(1 for kw in keywords if kw in user_input_lower)
            if score > 0:
                scores[task_type] = score
        
        # Return the task type with highest score
        if scores:
            return max(scores, key=scores.get)
        else:
            return "unknown"
    
    # ==================== Competence Map ====================
    
    def record_task_execution(self, user_input: str, success: bool, 
                              duration: float = None, tool_calls_count: int = 0,
                              error_type: str = None, user_feedback: str = None,
                              context_id: str = None):
        """Record task execution result, update competence map
        
        Args:
            context_id: 可选，关联的上下文ID（用于分析不同话题下的表现）
        """
        task_type = self._classify_task(user_input)
        
        # Initialize task type data
        if task_type not in self.competence_map["task_types"]:
            self.competence_map["task_types"][task_type] = {
                "total_count": 0,
                "success_count": 0,
                "fail_count": 0,
                "avg_duration": None,
                "success_rate": 0.0,
                "confidence": 0.5,
                "recent_results": [],
                "common_errors": {},
                "last_success": None,
                "last_failure": None,
                "context_stats": {}  # 新增：按context_id统计
            }
        
        stats = self.competence_map["task_types"][task_type]
        
        # Update counts
        stats["total_count"] += 1
        if success:
            stats["success_count"] += 1
            stats["last_success"] = datetime.now().isoformat()
        else:
            stats["fail_count"] += 1
            stats["last_failure"] = datetime.now().isoformat()
            if error_type:
                stats["common_errors"][error_type] = stats["common_errors"].get(error_type, 0) + 1
        
        # Update success rate
        stats["success_rate"] = stats["success_count"] / stats["total_count"]
        
        # Update average duration
        if duration is not None:
            if stats["avg_duration"] is None:
                stats["avg_duration"] = duration
            else:
                stats["avg_duration"] = (stats["avg_duration"] * (stats["total_count"] - 1) + duration) / stats["total_count"]
        
        # Update confidence (based on sample size and success rate)
        sample_factor = min(1.0, stats["total_count"] / 20.0)
        stats["confidence"] = stats["success_rate"] * sample_factor + 0.3 * (1 - sample_factor)
        
        # Record recent results (keep max 10)
        result_record = {
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "duration": duration,
            "error_type": error_type,
            "user_feedback": user_feedback,
            "context_id": context_id  # 新增：记录上下文ID
        }
        stats["recent_results"].append(result_record)
        if len(stats["recent_results"]) > 10:
            stats["recent_results"] = stats["recent_results"][-10:]
        
        # 新增：按context_id统计（分析不同话题下的表现）
        if context_id:
            if context_id not in stats["context_stats"]:
                stats["context_stats"][context_id] = {
                    "count": 0,
                    "success": 0,
                    "last_time": None
                }
            stats["context_stats"][context_id]["count"] += 1
            if success:
                stats["context_stats"][context_id]["success"] += 1
            stats["context_stats"][context_id]["last_time"] = datetime.now().isoformat()
        
        # Update timestamp
        self.competence_map["last_updated"] = datetime.now().isoformat()
        
        # Save
        self._save_json(self.competence_file, self.competence_map)
        
        # Check for blind spots
        self._check_blindspots(task_type, stats)
    
    def get_competence_map(self) -> Dict:
        """Get competence map (external interface)"""
        return self.competence_map
    
    def get_confidence(self, task_type: str = None, user_input: str = None) -> float:
        """Get confidence for a task type"""
        if user_input:
            task_type = self._classify_task(user_input)
        
        if task_type and task_type in self.competence_map["task_types"]:
            return self.competence_map["task_types"][task_type]["confidence"]
        return 0.3
    
    def get_best_task_types(self, limit: int = 5) -> List[Tuple]:
        """Get best task types (sorted by confidence)"""
        task_list = []
        for task_type, stats in self.competence_map["task_types"].items():
            task_list.append((task_type, stats["confidence"], stats["success_rate"], stats["total_count"]))
        
        task_list.sort(key=lambda x: x[1], reverse=True)
        return task_list[:limit]
    
    def get_worst_task_types(self, limit: int = 5) -> List[Tuple]:
        """Get worst task types"""
        task_list = []
        for task_type, stats in self.competence_map["task_types"].items():
            if stats["total_count"] >= 3:
                task_list.append((task_type, stats["confidence"], stats["success_rate"], stats["total_count"]))
        
        task_list.sort(key=lambda x: x[1])
        return task_list[:limit]
    
    # ==================== Blind Spot Detection ====================
    
    def _check_blindspots(self, task_type: str, stats: dict):
        """Check if need to mark as blind spot"""
        is_blindspot = False
        reason = ""
        
        # Conditions for blind spot:
        # 1. Failure rate > 50% and sample size >= 5
        # 2. Consecutive failures >= 3
        # 3. No success in over 30 days
        
        if stats["fail_count"] >= 5 and stats["success_rate"] < 0.5:
            is_blindspot = True
            reason = f"High failure rate ({stats['success_rate']:.1%})"
        
        recent = stats["recent_results"]
        if len(recent) >= 3 and all(not r["success"] for r in recent[-3:]):
            is_blindspot = True
            reason = "Consecutive failures 3+ times"
        
        if stats["last_success"]:
            last_success_time = datetime.fromisoformat(stats["last_success"])
            if datetime.now() - last_success_time > timedelta(days=30) and stats["total_count"] >= 5:
                is_blindspot = True
                reason = "No success in over 30 days"
        
        if is_blindspot:
            blindspot_entry = {
                "task_type": task_type,
                "identified_at": datetime.now().isoformat(),
                "reason": reason,
                "stats": {
                    "success_rate": stats["success_rate"],
                    "total_count": stats["total_count"],
                    "common_errors": stats["common_errors"]
                }
            }
            
            existing = [b for b in self.blindspots["identified"] if b["task_type"] == task_type]
            if not existing:
                self.blindspots["identified"].append(blindspot_entry)
                print(f"Blind spot detected: {task_type} - {reason}")
                self._save_json(self.blindspots_file, self.blindspots)
    
    def get_blindspots(self) -> List[Dict]:
        """Get identified blind spots"""
        return self.blindspots["identified"]
    
    def resolve_blindspot(self, task_type: str):
        """Mark blind spot as resolved"""
        self.blindspots["identified"] = [
            b for b in self.blindspots["identified"] if b["task_type"] != task_type
        ]
        self._save_json(self.blindspots_file, self.blindspots)
        print(f"Blind spot resolved: {task_type}")
    
    # ==================== Self-Assessment ====================
    
    def self_assess(self, user_input: str, final_answer: str, task_result: Any, user_feedback: str = None) -> Dict:
        """Self-assessment: score and reflect on this conversation
        
        Args:
            user_feedback: User feedback, format like "5 stars", "3 points", etc.
        """
        task_type = self._classify_task(user_input)
        stats = self.competence_map["task_types"].get(task_type, {})
        
        # Base scores (based on historical performance)
        accuracy_score = stats.get("success_rate", 0.5)
        efficiency_score = self._evaluate_efficiency(task_result, stats)
        
        # Simple evaluation
        helpfulness_score = self._evaluate_helpfulness(user_input, final_answer)
        clarity_score = self._evaluate_clarity(final_answer)
        
        # User feedback affects total score
        user_feedback_score = None
        if user_feedback:
            user_feedback_score = self._parse_user_feedback(user_feedback)
            if user_feedback_score is not None:
                # User feedback weight: 30%
                helpfulness_score = (helpfulness_score * 0.7) + (user_feedback_score * 0.3)
        
        overall_score = (accuracy_score + helpfulness_score + efficiency_score + clarity_score) / 4
        
        # Generate reflection
        reflection = self._generate_reflection(task_type, overall_score, stats)
        
        # Improvement suggestions
        suggestions = self._generate_improvement_suggestions(task_type, overall_score, stats)
        
        result = {
            "task_type": task_type,
            "accuracy_score": round(accuracy_score, 2),
            "helpfulness_score": round(helpfulness_score, 2),
            "efficiency_score": round(efficiency_score, 2),
            "clarity_score": round(clarity_score, 2),
            "overall_score": round(overall_score, 2),
            "user_feedback_score": round(user_feedback_score, 2) if user_feedback_score else None,
            "reflection": reflection,
            "improvement_suggestions": suggestions,
            "timestamp": datetime.now().isoformat()
        }
        
        # Save reflection record
        self._save_reflection(result)
        
        return result
    
    def _parse_user_feedback(self, feedback: str) -> Optional[float]:
        """Parse user feedback, convert to 0-1 score"""
        feedback = feedback.strip()
        
        # Match star rating: 5 stars, 4 stars, etc.
        import re
        star_match = re.search(r'(\d+)\s*stars?', feedback, re.IGNORECASE)
        if star_match:
            stars = int(star_match.group(1))
            return min(5, max(1, stars)) / 5.0
        
        # Match score: 5 points, 4 points, etc.
        score_match = re.search(r'(\d+)\s*points?', feedback, re.IGNORECASE)
        if score_match:
            score = int(score_match.group(1))
            return min(5, max(1, score)) / 5.0
        
        # Match direct number: 5, 4, 3, etc.
        num_match = re.match(r'^(\d+)$', feedback)
        if num_match:
            num = int(num_match.group(1))
            if 1 <= num <= 5:
                return num / 5.0
        
        # Match text evaluation
        positive_words = ['great', 'excellent', 'good', 'perfect', 'satisfied', 'nice']
        negative_words = ['bad', 'terrible', 'poor', 'unsatisfied', 'wrong']
        
        feedback_lower = feedback.lower()
        for word in positive_words:
            if word in feedback_lower:
                return 0.9
        for word in negative_words:
            if word in feedback_lower:
                return 0.3
        
        return None
    
    def _evaluate_efficiency(self, task_result: Any, stats: dict) -> float:
        """Evaluate efficiency (whether used least steps)"""
        if not task_result or not hasattr(task_result, 'steps'):
            return 0.5
        
        steps = task_result.steps
        avg_steps = stats.get("avg_steps", steps)
        
        if steps <= avg_steps * 0.5:
            return 1.0
        elif steps <= avg_steps:
            return 0.8
        elif steps <= avg_steps * 1.5:
            return 0.6
        else:
            return 0.4
    
    def _evaluate_helpfulness(self, user_input: str, final_answer: str) -> float:
        """Evaluate helpfulness (simple heuristic)"""
        score = 0.7
        
        if 50 < len(final_answer) < 2000:
            score += 0.1
        
        user_keywords = set(user_input.lower().split())
        answer_keywords = set(final_answer.lower().split())
        overlap = len(user_keywords & answer_keywords) / max(len(user_keywords), 1)
        score += overlap * 0.2
        
        return min(1.0, score)
    
    def _evaluate_clarity(self, final_answer: str) -> float:
        """Evaluate clarity"""
        score = 0.7
        
        if any(c in final_answer for c in ['•', '-', '1.', '###', '**']):
            score += 0.1
        
        paragraphs = final_answer.split('\n\n')
        if all(len(p) < 300 for p in paragraphs):
            score += 0.1
        
        if len(set(final_answer.split())) > len(final_answer.split()) * 0.3:
            score += 0.1
        
        return min(1.0, score)
    
    def _generate_reflection(self, task_type: str, overall_score: float, stats: dict) -> str:
        """Generate reflection text"""
        if overall_score >= 0.8:
            return f"Task {task_type} performed well, keep it up."
        elif overall_score >= 0.6:
            return f"Task {task_type} performed average, room for improvement."
        else:
            return f"Task {task_type} performed poorly, needs improvement."
    
    def _generate_improvement_suggestions(self, task_type: str, overall_score: float, stats: dict) -> List[str]:
        """Generate improvement suggestions"""
        suggestions = []
        
        if overall_score < 0.6:
            suggestions.append(f"Consider generating specialized skill doc for {task_type}")
        
        if stats.get("common_errors"):
            top_error = max(stats["common_errors"], key=stats["common_errors"].get)
            suggestions.append(f"Common error type: {top_error}, need targeted improvement")
        
        if stats.get("confidence", 0) < 0.5:
            suggestions.append(f"Low confidence in {task_type}, suggest more practice")
        
        return suggestions
    
    def _save_reflection(self, reflection: dict):
        """Save reflection record"""
        self.reflections["recent"].append(reflection)
        
        if len(self.reflections["recent"]) > 20:
            self.reflections["recent"] = self.reflections["recent"][-20:]
        
        self._update_patterns(reflection)
        
        self._save_json(self.reflection_file, self.reflections)
    
    def _update_patterns(self, reflection: dict):
        """Identify patterns from reflections"""
        task_type = reflection["task_type"]
        
        if task_type not in self.reflections["patterns"]:
            self.reflections["patterns"][task_type] = {
                "avg_score": reflection["overall_score"],
                "count": 1,
                "trend": "stable"
            }
        else:
            pattern = self.reflections["patterns"][task_type]
            old_avg = pattern["avg_score"]
            pattern["count"] += 1
            pattern["avg_score"] = (old_avg * (pattern["count"] - 1) + reflection["overall_score"]) / pattern["count"]
            
            if reflection["overall_score"] > old_avg + 0.1:
                pattern["trend"] = "improving"
            elif reflection["overall_score"] < old_avg - 0.1:
                pattern["trend"] = "declining"
            else:
                pattern["trend"] = "stable"
    
    # ==================== Help Strategy ====================
    
    def should_ask_help(self, user_input: str) -> Tuple[bool, str, str]:
        """Determine if need to ask for help
        
        Returns: (should_ask: bool, reason: str, suggestion: str)
        """
        task_type = self._classify_task(user_input)
        confidence = self.get_confidence(task_type)
        
        blindspots = [b for b in self.blindspots["identified"] if b["task_type"] == task_type]
        if blindspots:
            return (True, f"This is a known blind spot: {blindspots[0]['reason']}", 
                    "Suggestion: Try decomposing the task, or tell me the steps you expect")
        
        if confidence < 0.3 and task_type != "unknown":
            return (True, f"Low confidence in {task_type} task ({confidence:.0%})",
                    "Suggestion: I will try my best, but may need your guidance")
        
        if task_type in self.competence_map["task_types"]:
            stats = self.competence_map["task_types"][task_type]
            if stats["total_count"] < 3 and stats.get("fail_count", 0) > 0:
                return (True, "I have not done this task much, may make mistakes",
                        "Suggestion: If my answer is wrong, please tell me the correct approach")
        
        return (False, "", "")
    
    def generate_learning_plan(self) -> Dict:
        """Generate learning plan: targeted improvement for blind spots"""
        blindspots = self.get_blindspots()
        weak_types = self.get_worst_task_types(limit=3)
        
        plan = {
            "target_blindspots": [],
            "target_weak_types": [],
            "actions": []
        }
        
        for bs in blindspots:
            plan["target_blindspots"].append({
                "task_type": bs["task_type"],
                "reason": bs["reason"]
            })
            plan["actions"].append(f"Generate specialized skill doc for {bs['task_type']}")
            plan["actions"].append(f"Collect good examples for {bs['task_type']} and learn")
        
        for wt in weak_types:
            plan["target_weak_types"].append({
                "task_type": wt[0],
                "confidence": wt[1]
            })
            plan["actions"].append(f"Practice more on {wt[0]} (current confidence {wt[1]:.0%})")
        
        return plan
    
    # ==================== Report Generation ====================
    
    def generate_status_report(self) -> str:
        """Generate metacognition status report (human-readable)"""
        lines = []
        lines.append("dogeey Metacognition Status Report")
        lines.append("=" * 50)
        
        # Competence map overview
        lines.append("\nCompetence Map:")
        best = self.get_best_task_types(limit=3)
        if best:
            lines.append("  Best at:")
            for task_type, conf, rate, count in best:
                lines.append(f"    - {task_type}: confidence {conf:.0%}, success rate {rate:.0%} ({count} times)")
        
        worst = self.get_worst_task_types(limit=3)
        if worst:
            lines.append("  Worst at:")
            for task_type, conf, rate, count in worst:
                lines.append(f"    - {task_type}: confidence {conf:.0%}, success rate {rate:.0%} ({count} times)")
        
        # Blind spots
        blindspots = self.get_blindspots()
        if blindspots:
            lines.append("\nBlind Spots:")
            for bs in blindspots:
                lines.append(f"  - {bs['task_type']}: {bs['reason']}")
        else:
            lines.append("\nNo blind spots detected")
        
        # Recent reflections
        if self.reflections["recent"]:
            lines.append("\nRecent Reflections:")
            for ref in self.reflections["recent"][-3:]:
                lines.append(f"  - [{ref['task_type']}] Overall score {ref['overall_score']:.2f}")
                lines.append(f"    {ref['reflection']}")
        
        return "\n".join(lines)
    
    def generate_daily_reflection(self) -> str:
        """Generate daily reflection (to be called by cron or manually)"""
        lines = []
        lines.append("dogeey Daily Reflection")
        lines.append("=" * 50)
        lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        
        # Today's statistics
        today = datetime.now().date()
        today_reflections = [
            r for r in self.reflections["recent"]
            if datetime.fromisoformat(r["timestamp"]).date() == today
        ]
        
        if today_reflections:
            lines.append(f"\nToday's conversations: {len(today_reflections)}")
            avg_score = sum(r["overall_score"] for r in today_reflections) / len(today_reflections)
            lines.append(f"Average score: {avg_score:.2f}")
            
            # Task type distribution
            task_counts = {}
            for r in today_reflections:
                task_type = r["task_type"]
                task_counts[task_type] = task_counts.get(task_type, 0) + 1
            
            lines.append("\nTask types today:")
            for task_type, count in sorted(task_counts.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  - {task_type}: {count} times")
        else:
            lines.append("\nNo conversations today")
        
        # Patterns
        if self.reflections["patterns"]:
            lines.append("\nLearning Patterns:")
            for task_type, pattern in self.reflections["patterns"].items():
                lines.append(f"  - {task_type}: {pattern['trend']} (avg score: {pattern['avg_score']:.2f})")
        
        # Suggestions
        plan = self.generate_learning_plan()
        if plan.get("actions"):
            lines.append("\nSuggestions:")
            for action in plan["actions"][:3]:  # Top 3
                lines.append(f"  - {action}")
        
        return "\n".join(lines)
