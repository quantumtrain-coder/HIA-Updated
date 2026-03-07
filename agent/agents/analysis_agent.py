"""Analysis agent for blood report processing - Bedrock edition."""

from datetime import datetime, timedelta
from services.bedrock_service import BedrockModelManager


class AnalysisAgent:
    """Analyzes blood reports using Bedrock models with in-context learning."""

    def __init__(self):
        self.model_manager = BedrockModelManager()
        self.analysis_count = 0
        self.last_analysis = datetime.now()
        self.analysis_limit = 15
        self.knowledge_base = {}

    def check_rate_limit(self):
        time_until_reset = timedelta(days=1) - (datetime.now() - self.last_analysis)
        hours, remainder = divmod(time_until_reset.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if time_until_reset.days < 0:
            self.analysis_count = 0
            self.last_analysis = datetime.now()
            return True, None

        if self.analysis_count >= self.analysis_limit:
            return False, f"Daily limit reached. Reset in {hours}h {minutes}m"
        return True, None

    def analyze_report(self, data, system_prompt, check_only=False):
        can_analyze, error_msg = self.check_rate_limit()
        if not can_analyze:
            return {"success": False, "error": error_msg}
        if check_only:
            return can_analyze, error_msg

        processed = self._preprocess_data(data)
        result = self.model_manager.generate(system_prompt, str(processed))

        if result["success"]:
            self.analysis_count += 1
            self.last_analysis = datetime.now()

        return result

    def _preprocess_data(self, data):
        if isinstance(data, dict):
            return {
                "patient_name": data.get("patient_name", ""),
                "age": data.get("age", ""),
                "gender": data.get("gender", ""),
                "report": data.get("report", ""),
            }
        return data
