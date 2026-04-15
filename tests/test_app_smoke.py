import os
import tempfile
import unittest


os.environ.setdefault("QWEN_API_KEY", "test-qwen-key")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(tempfile.gettempdir(), 'personalized_learning_assistant_smoke.db')}",
)

from fastapi.testclient import TestClient

from main import app


class AppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_root_endpoint_is_available(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "AI 后端服务已启动！"})

    def test_core_routes_are_registered(self):
        registered_paths = {route.path for route in app.routes}
        expected_paths = {
            "/api/agent/chat",
            "/api/user/profile",
            "/api/interview/start",
            "/api/architect/generate-course-plan",
            "/api/tutor/respond",
            "/api/profiler/analyze-interaction",
            "/api/clerk/generate-note",
            "/api/progress/update",
            "/api/concierge/respond",
            "/api/onboarding/generate-syllabus",
            "/api/notes/list/{user_id}",
            "/api/study/generate-questions",
        }

        self.assertTrue(expected_paths.issubset(registered_paths))


if __name__ == "__main__":
    unittest.main()
