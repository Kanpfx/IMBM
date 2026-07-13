import json

from agents.base import BaseAgent
from agents.prompts.immediate import (
    create_im_prompt,
    get_action_format_prompt,
    required_predicted_observation_sections,
)
from utils.format import constrcut_openai_qa, extract_code


class ImAgent(BaseAgent):
    """IM 负责把当前观测和 BM 指令转换成可执行动作。"""

    def __init__(self, race: str, include_observation: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.race = race
        self.include_observation = include_observation
        self.max_retry_attempts = 2
        self.think = []
        self.chat_history = []
        self.last_trace = {"calls": [], "verifier": []}

    def _parse_response(self, response: str) -> tuple[dict, str]:
        try:
            code = extract_code(response)
            if not code:
                raise ValueError("Response must contain a JSON code block wrapped with triple backticks.")
            payload = json.loads(code)
            if not isinstance(payload, dict):
                raise ValueError(
                    "IM response must be a JSON object with actions, request_background, and background_reason."
                )
            predicted_observation = None
            # 预测观测是可选输出，默认关闭以减少 token 和 schema 负担。
            if self.include_observation:
                if "predicted_observation" not in payload:
                    raise ValueError("Missing required key: predicted_observation.")
                predicted_observation = payload["predicted_observation"]
                if isinstance(predicted_observation, (dict, list)):
                    predicted_observation = json.dumps(predicted_observation, ensure_ascii=False)
                else:
                    predicted_observation = str(predicted_observation)
                if not predicted_observation.strip():
                    raise ValueError("`predicted_observation` must be a non-empty observation snapshot.")
                missing_sections = [
                    section
                    for section in required_predicted_observation_sections
                    if section not in predicted_observation
                ]
                if missing_sections:
                    raise ValueError(
                        "`predicted_observation` must be formatted as a formal observation snapshot. "
                        + "Missing sections: "
                        + ", ".join(missing_sections)
                    )
            actions = payload.get("actions", [])
            if not isinstance(actions, list):
                raise ValueError("`actions` must be a list.")
            return {
                "predicted_observation": predicted_observation,
                "actions": actions,
                "request_background": bool(payload.get("request_background", False)),
                "background_reason": str(payload.get("background_reason", "")),
            }, ""
        except Exception as exc:
            return {
                "predicted_observation": None,
                "actions": [],
                "request_background": False,
                "background_reason": "",
            }, str(exc)

    def _safe_parse(self, response: str) -> dict:
        # 最终兜底：解析失败时请求 BM 介入，但不让主循环崩溃。
        payload, error = self._parse_response(response)
        if error:
            return {
                "predicted_observation": None,
                "actions": [],
                "request_background": True,
                "background_reason": "IM response could not be parsed.",
            }
        return payload

    def _refine_schema_prompt(self, error: str) -> str:
        return (
            "The previous IM response failed JSON syntax/schema validation:\n"
            + error
            + "\nReturn only a complete IM JSON object wrapped with triple backticks in this schema:\n"
            + get_action_format_prompt(self.include_observation)
        )

    def _refine_actions_prompt(self, verification_message: str) -> str:
        return (
            "The previous IM actions failed validation:\n"
            + verification_message
            + "\nAnalyze the issue silently and return only a complete refined IM JSON object wrapped with triple backticks in this schema:\n"
            + get_action_format_prompt(self.include_observation)
        )

    def run(self, obs_text: str, plan_text: str | None = None, verifier=None):
        self.think = []
        self.chat_history = []
        self.last_trace = {"calls": [], "verifier": []}

        prompt = create_im_prompt(obs_text, plan_text, include_observation=self.include_observation)
        # 首次回答先做 JSON/schema 检查，再进入动作合法性检查。
        response, messages = self.llm_client.call(
            prompt=prompt,
            **self.generation_config,
            need_json=True,
        )
        stage = "initial"
        self.last_trace["calls"].append({"stage": stage, "prompt": prompt, "response": response})
        self.think.append([response])
        self.chat_history.append(messages)

        history = constrcut_openai_qa(prompt, response)
        payload, parse_error = self._parse_response(response)
        verification_record = {
            "stage": stage,
            "schema_error": parse_error,
            "actions_ok": None,
            "actions_error": "",
        }
        self.last_trace["verifier"].append(verification_record)
        requested_background = payload["request_background"]
        requested_reason = payload["background_reason"]
        refine_number = 0

        for _ in range(self.max_retry_attempts):
            if parse_error:
                # schema 错误直接把错误反馈给 IM，让它按同一 schema 重写。
                self.think[-1].append(parse_error)
                refine_prompt = self._refine_schema_prompt(parse_error)
                response, messages = self.llm_client.call(
                    prompt=refine_prompt,
                    history=history,
                    **self.generation_config,
                    need_json=True,
                )
                refine_number += 1
                stage = f"refine_{refine_number}"
                self.last_trace["calls"].append(
                    {"stage": stage, "prompt": refine_prompt, "response": response}
                )
                self.think.append([response])
                self.chat_history.append(messages)
                history.extend(constrcut_openai_qa(refine_prompt, response))
                payload, parse_error = self._parse_response(response)
                verification_record = {
                    "stage": stage,
                    "schema_error": parse_error,
                    "actions_ok": None,
                    "actions_error": "",
                }
                self.last_trace["verifier"].append(verification_record)
                if payload["request_background"]:
                    requested_background = True
                    requested_reason = payload["background_reason"] or requested_reason
                continue

            if not verifier:
                break

            ok, verification_message = verifier(payload["actions"])
            self.think[-1].append(verification_message)
            verification_record["actions_ok"] = ok
            verification_record["actions_error"] = verification_message
            if ok:
                break

            # 动作不合法时保留上下文，让 IM 只修动作而不重新发散。
            refine_prompt = self._refine_actions_prompt(verification_message)
            response, messages = self.llm_client.call(
                prompt=refine_prompt,
                history=history,
                **self.generation_config,
                need_json=True,
            )
            refine_number += 1
            stage = f"refine_{refine_number}"
            self.last_trace["calls"].append(
                {"stage": stage, "prompt": refine_prompt, "response": response}
            )
            self.think.append([response])
            self.chat_history.append(messages)
            history.extend(constrcut_openai_qa(refine_prompt, response))
            payload, parse_error = self._parse_response(response)
            verification_record = {
                "stage": stage,
                "schema_error": parse_error,
                "actions_ok": None,
                "actions_error": "",
            }
            self.last_trace["verifier"].append(verification_record)
            if payload["request_background"]:
                requested_background = True
                requested_reason = payload["background_reason"] or requested_reason

        payload = self._safe_parse(response)
        # 即使最后一次 refined response 没保留请求，也不丢失前序 BM 请求信号。
        if requested_background:
            payload["request_background"] = True
            payload["background_reason"] = payload["background_reason"] or requested_reason
        return (
            payload["predicted_observation"],
            payload["actions"],
            payload["request_background"],
            payload["background_reason"],
            self.think,
            self.chat_history,
        )
