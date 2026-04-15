import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ.setdefault("QWEN_API_KEY", "test-qwen-key")

from app.db.models import (
    Base,
    CognitiveProfileObservation,
    InterviewResult,
    InterviewSession,
    UserCognitiveProfile,
    UserLearningProgress,
    UserSyllabus,
)
from app.schemas.architect import ArchitectGenerateRequest
from app.schemas.interview import ReplyInterviewRequest, StartInterviewRequest
from app.schemas.profiler import ProfilerAnalyzeRequest
from app.schemas.progress import ProgressUpdateRequest
from app.services.architect_service import generate_course_plan_flow
from app.services.interview_service import reply_interview_flow, start_interview_flow
from app.services.profiler_service import analyze_learning_interaction_flow
from app.services.progress_service import (
    get_learning_progress_flow,
    update_learning_progress_flow,
)


def make_openai_json_response(payload):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
            )
        ]
    )


def make_course_plan():
    return {
        "title": "Java 并发精讲",
        "description": "按学习者基础定制的课程。",
        "learner_profile": {
            "user_level": "beginner",
            "learning_goal": "理解线程池并能看懂项目代码",
            "pain_points": ["线程池参数"],
            "preferred_style": ["类比"],
            "recommended_start_point": "线程与线程池基础",
        },
        "chapters": [
            {
                "id": "chapter_1",
                "title": "第一章：线程与线程池",
                "description": "先建立并发基础。",
                "learning_goals": ["理解线程池的角色"],
                "sections": [
                    {
                        "id": "section_1_1",
                        "title": "1.1 线程池基础",
                        "objective": "知道线程池为什么存在",
                        "key_points": ["核心线程数", "任务队列"],
                        "practice_questions": [],
                    },
                    {
                        "id": "section_1_2",
                        "title": "1.2 线程池参数",
                        "objective": "理解参数如何影响行为",
                        "key_points": ["maximumPoolSize", "拒绝策略"],
                        "practice_questions": [],
                    },
                ],
            }
        ],
    }


class ServiceFlowTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_interview_flow_can_start_and_finish_with_structured_result(self):
        start_request = StartInterviewRequest(
            user_id="u_interview",
            course_id="java_concurrency_101",
            course_title="Java 并发编程",
            key_topics=["线程", "线程池"],
        )

        start_response = start_interview_flow(start_request, self.db)

        self.assertEqual(start_response["status"], "success")
        self.assertFalse(start_response["finished"])
        self.assertEqual(start_response["current_slots"]["foundation"], "missing")

        with patch(
            "app.services.interview_service.analyze_interview_turn",
            return_value={
                "slot_updates": {
                    "foundation": {"status": "filled", "value": "了解一点 Java 语法，还没系统学过并发", "evidence": "用户说明只学过基础"},
                    "goal": {"status": "filled", "value": "工作中想看懂线程池相关代码", "evidence": "用户提到工作目标"},
                    "pain_point": {"status": "filled", "value": ["线程池参数"], "evidence": "用户明确提到参数看不懂"},
                    "preference": {"status": "filled", "value": ["类比", "先例子后概念"], "evidence": "用户说明偏好类比"},
                },
                "should_finish": True,
                "termination_reason": "enough_information",
                "assistant_reply": "明白了，我已经了解你的情况了，接下来会按你的基础来安排内容。",
                "interview_summary": {
                    "user_level": "beginner",
                    "confidence": 0.88,
                    "learning_goal": "工作中想看懂线程池相关代码",
                    "deadline": None,
                    "preferred_style": ["类比", "先例子后概念"],
                    "pain_points": ["线程池参数"],
                    "known_topics": ["Java 基础语法"],
                    "unknown_topics": ["线程池参数"],
                    "motivation": "工作需要",
                    "recommended_start_point": "线程与线程池基础",
                },
            },
        ):
            reply_response = reply_interview_flow(
                ReplyInterviewRequest(
                    session_id=start_response["session_id"],
                    user_message="我主要是工作里会碰到线程池，想看懂参数含义。",
                ),
                self.db,
            )

        self.assertTrue(reply_response["finished"])
        self.assertEqual(
            reply_response["interview_result"]["interview_summary"]["learning_goal"],
            "工作中想看懂线程池相关代码",
        )

        session = self.db.query(InterviewSession).filter_by(id=start_response["session_id"]).first()
        result = self.db.query(InterviewResult).filter_by(session_id=start_response["session_id"]).first()
        self.assertIsNotNone(session)
        self.assertEqual(session.status, "completed")
        self.assertIsNotNone(result)

    def test_interview_flow_uses_local_fallback_when_llm_analysis_fails(self):
        start_response = start_interview_flow(
            StartInterviewRequest(
                user_id="u_interview_fallback",
                course_id="python_basic_101",
                course_title="Python 基础",
                key_topics=["变量", "函数"],
            ),
            self.db,
        )

        with patch(
            "app.services.interview_service.analyze_interview_turn",
            side_effect=RuntimeError("llm unavailable"),
        ):
            reply_response = reply_interview_flow(
                ReplyInterviewRequest(
                    session_id=start_response["session_id"],
                    user_message="学过，但是忘得差不多了。",
                ),
                self.db,
            )

        self.assertFalse(reply_response["finished"])
        self.assertEqual(reply_response["current_slots"]["foundation"], "filled")
        self.assertIn("主要更偏向工作、面试、考试，还是先打基础", reply_response["agent_reply"])

        session = self.db.query(InterviewSession).filter_by(id=start_response["session_id"]).first()
        self.assertEqual(session.slot_state["foundation"]["value"], "学过，但是忘得差不多了。")
        self.assertEqual(session.question_count, 2)

    def test_interview_flow_rephrases_low_signal_reply_instead_of_repeating_same_question(self):
        start_response = start_interview_flow(
            StartInterviewRequest(
                user_id="u_interview_retry",
                course_id="python_basic_101",
                course_title="Python 基础",
                key_topics=["变量", "函数"],
            ),
            self.db,
        )

        with patch(
            "app.services.interview_service.analyze_interview_turn",
            return_value={},
        ):
            reply_response = reply_interview_flow(
                ReplyInterviewRequest(
                    session_id=start_response["session_id"],
                    user_message="1",
                ),
                self.db,
            )

        self.assertFalse(reply_response["finished"])
        self.assertEqual(reply_response["current_slots"]["foundation"], "missing")
        self.assertIn("完全没学过、学过一点，还是学过但忘得差不多了", reply_response["agent_reply"])

    def test_architect_flow_generates_and_persists_course_plan(self):
        interview_result = {
            "interview_summary": {
                "user_level": "beginner",
                "learning_goal": "理解线程池并能看懂项目代码",
                "pain_points": ["线程池参数"],
                "preferred_style": ["类比"],
                "motivation": "工作需要",
                "recommended_start_point": "线程与线程池基础",
            },
            "interview_trace": [],
            "termination_reason": "enough_information",
        }
        raw_plan = {
            "title": "Java 并发精讲",
            "description": "定制课程",
            "course_objectives": ["理解线程池"],
            "recommended_start_point": "线程与线程池基础",
            "chapters": [
                {
                    "title": "第一章：线程与线程池",
                    "description": "基础章节",
                    "learning_goals": ["理解线程池的角色"],
                    "sections": [
                        {
                            "title": "1.1 线程池基础",
                            "objective": "知道线程池为什么存在",
                            "key_points": ["核心线程数"],
                            "practice_questions": [
                                {
                                    "type": "choice",
                                    "question": "线程池的核心作用是什么？",
                                    "options": ["复用线程", "增加内存"],
                                    "answer": "A",
                                    "explanation": "线程池通过复用线程减少创建销毁开销。",
                                    "hint": "想想频繁创建线程的成本。",
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        with patch(
            "app.services.architect_service.client.chat.completions.create",
            return_value=make_openai_json_response(raw_plan),
        ):
            response = generate_course_plan_flow(
                ArchitectGenerateRequest(
                    user_id="u_architect",
                    course_id="java_concurrency_101",
                    course_title="Java 并发编程",
                    key_topics=["线程", "线程池"],
                    interview_result=interview_result,
                ),
                self.db,
            )

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["data"]["title"], "Java 并发精讲")
        self.assertEqual(response["data"]["chapters"][0]["sections"][0]["practice_questions"][0]["id"], "q_1_1_1")

        saved = self.db.query(UserSyllabus).filter_by(
            user_id="u_architect",
            course_id="java_concurrency_101",
        ).first()
        self.assertIsNotNone(saved)
        self.assertEqual(saved.syllabus_data["learner_profile"]["learning_goal"], "理解线程池并能看懂项目代码")

    def test_architect_flow_backfills_section_titles_and_questions(self):
        interview_result = {
            "interview_summary": {
                "user_level": "beginner",
                "learning_goal": "先把 JavaScript 基础打牢",
                "pain_points": ["概念容易混"],
                "preferred_style": ["先例子后概念"],
                "motivation": "想做网页交互",
                "recommended_start_point": "变量与数据类型",
            },
            "interview_trace": [],
            "termination_reason": "enough_information",
        }
        raw_plan = {
            "title": "JavaScript",
            "description": "定制课程",
            "course_objectives": ["掌握 JavaScript 基础"],
            "chapters": [
                {
                    "title": "JavaScript 基础概念与运行环境",
                    "description": "基础章节",
                    "learning_goals": ["建立基础认知"],
                    "sections": [
                        {
                            "title": "",
                            "objective": "",
                            "key_points": [],
                            "practice_questions": [],
                        }
                    ],
                }
            ],
        }

        with patch(
            "app.services.architect_service.client.chat.completions.create",
            return_value=make_openai_json_response(raw_plan),
        ):
            response = generate_course_plan_flow(
                ArchitectGenerateRequest(
                    user_id="u_architect_fill",
                    course_id="javascript",
                    course_title="JavaScript",
                    key_topics=["变量与数据类型", "条件判断"],
                    interview_result=interview_result,
                ),
                self.db,
            )

        section = response["data"]["chapters"][0]["sections"][0]
        self.assertTrue(section["title"])
        self.assertNotIn("未命名", section["title"])
        self.assertTrue(section["objective"])
        self.assertGreaterEqual(len(section["practice_questions"]), 2)
        self.assertTrue(all(question["question"] for question in section["practice_questions"]))
        self.assertGreaterEqual(response["data"]["metadata"]["question_count"], 2)

    def test_profiler_flow_updates_profile_and_writes_observation(self):
        self.db.add(
            UserSyllabus(
                user_id="u_profiler",
                course_id="java_concurrency_101",
                syllabus_data=make_course_plan(),
            )
        )
        self.db.commit()

        analysis_payload = {
            "should_update": True,
            "summary": "用户明确表示类比和一步提示更有效。",
            "profile_updates": {
                "preferred_explanation_styles": ["类比"],
                "hint_preference": "一次只给一步提示",
                "motivation_hooks": ["工作代码能看懂更有动力"],
                "friction_points": ["抽象定义太多会晕"],
            },
            "evidence": [
                {"signal": "用户说类比更容易听懂", "impact": "强化类比解释方式"}
            ],
            "confidence": 0.9,
        }

        with patch(
            "app.services.profiler_service.client.chat.completions.create",
            return_value=make_openai_json_response(analysis_payload),
        ):
            response = analyze_learning_interaction_flow(
                ProfilerAnalyzeRequest(
                    user_id="u_profiler",
                    course_id="java_concurrency_101",
                    chapter_id="chapter_1",
                    section_id="section_1_1",
                    user_message="这个类比我听懂了，最好还是一步一步提示我。",
                    tutor_reply="我们先只看核心线程数这个参数。",
                    user_feedback="这样讲我更容易理解。",
                ),
                self.db,
            )

        self.assertTrue(response["updated"])
        self.assertEqual(response["profile"]["hint_preference"], "一次只给一步提示")
        self.assertIn("类比", response["profile"]["preferred_explanation_styles"])

        profile = self.db.query(UserCognitiveProfile).filter_by(user_id="u_profiler").first()
        observation = self.db.query(CognitiveProfileObservation).filter_by(user_id="u_profiler").first()
        self.assertIsNotNone(profile)
        self.assertIsNotNone(observation)
        self.assertEqual(observation.observation_json["summary"], "用户明确表示类比和一步提示更有效。")

    def test_progress_flow_updates_and_computes_metrics(self):
        self.db.add(
            UserSyllabus(
                user_id="u_progress",
                course_id="java_concurrency_101",
                syllabus_data=make_course_plan(),
            )
        )
        self.db.commit()

        update_response = update_learning_progress_flow(
            ProgressUpdateRequest(
                user_id="u_progress",
                course_id="java_concurrency_101",
                current_chapter_id="chapter_1",
                current_chapter_title="第一章：线程与线程池",
                current_section_id="section_1_1",
                current_section_title="1.1 线程池基础",
                completed_section_ids=["section_1_1"],
                event_type="complete_section",
                progress_meta={"source": "test"},
            ),
            self.db,
        )

        self.assertEqual(update_response["status"], "success")
        self.assertEqual(update_response["data"]["progress"]["section_total"], 2)
        self.assertEqual(update_response["data"]["progress"]["completed_section_count"], 1)
        self.assertEqual(update_response["data"]["progress"]["section_progress_percent"], 50.0)

        query_response = get_learning_progress_flow("u_progress", "java_concurrency_101", self.db)
        self.assertEqual(query_response["data"]["progress"]["current_section_id"], "section_1_1")

        progress_record = self.db.query(UserLearningProgress).filter_by(
            user_id="u_progress",
            course_id="java_concurrency_101",
        ).first()
        self.assertIsNotNone(progress_record)


if __name__ == "__main__":
    unittest.main()
