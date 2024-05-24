import time
import traceback
from app.parsers import (
    format_text,
    check_text_for_phrases,
    split_text_into_words,
    ClipboardContentParser,
    CurrentTimeAndDateParser,
    StateTransitionParser,
)
from app.tool_loader import ToolLoader
from app.config import Configuration
from app.state import ApplicationState
from app.transcript import Transcript
from app.io_output import TextToSpeech
from app.llm_agent import LargeLanguageModelAgent
from app.pkg.beep import BeepGenerator
from app.llm_provider import LanguageModelProvider
from app.io_input import UserInput
from app.my_print import print_text


class ConversationManager:
    def __init__(
            self,
            config: Configuration,
            state: ApplicationState,
            agent: LargeLanguageModelAgent,
            provider: LanguageModelProvider,
            collector: Transcript,
            tool_loader: ToolLoader,
            parser: StateTransitionParser,
            response: TextToSpeech,
            beep: BeepGenerator,
    ):
        self.beep = beep
        self.parser = parser
        self.agent = agent
        self.provider = provider
        self.tool_loader = tool_loader
        self.config = config
        self.state = state
        self.collector = collector
        self.response = response
        self.current_state_hash = None
        self.user_input = UserInput(config=self.config, state=self.state, transcript_collector=self.collector, beep=self.beep)

    def reload_agent(self, force: bool = False):
        if self.current_state_hash is None or self.current_state_hash != self.state.get_hash():
            self.current_state_hash = self.state.get_hash()
            force = True

        if force:
            print_text(state=self.state, text="Loading LLM...")
            self.agent.reload()

        return self.agent

    def add_text_to_file(self, who, text):
        if self.config.history_file is not None and self.config.history_file != "":
            with open(self.config.history_file, "a") as file:
                datetime = time.strftime("%Y-%m-%d %H:%M:%S")
                content = format_text(f"{datetime} {who}: {text}")
                file.write(content+"\n")

    def pre_parse_question(self) -> tuple[bool, bool]:
        if self.user_input.question_text == "":
            return False, False

        state_changed, stop = self.parser.quick_state_change(self.user_input.question_text)
        if state_changed or stop:
            return state_changed, stop

        input_was_changed = False
        if "pre-parsers" in self.config.settings:
            if "clipboard" in self.config.settings["pre-parsers"] and self.config.settings["pre-parsers"]["clipboard"]["enabled"]:
                if check_text_for_phrases(state=self.state, contains=True, phrases=["clipboard"], question=self.user_input.question_text):
                    changed, out = ClipboardContentParser().parse(self.user_input.question_text)
                    if changed:
                        input_was_changed = True
                        self.user_input.question_text = out

            if "time" in self.config.settings["pre-parsers"] and self.config.settings["pre-parsers"]["time"]["enabled"]:
                time_parser = CurrentTimeAndDateParser(timezone=self.config.prompt_replacements["timezone"], state=self.state)
                changed, out = time_parser.parse(self.user_input.question_text)
                if changed:
                    input_was_changed = True
                    self.user_input.question_text = out

        if input_was_changed:
            self.add_text_to_file("Question pre-parser", self.user_input.question_text)

        return False, False

    async def main_loop(self, first_question: str = ""):
        while self.state.is_stopped is False:
            stop = await self.question_answer(first_question)
            first_question = ""
            if stop:
                break

    async def question_answer(self, first_question: str = "") -> bool:
        print_text(state=self.state, text=f"\033[93m{self.state.input_model}\033[0m → \033[91;1;4m{self.state.llm_model}\033[0m ({self.state.llm_model_options['model']}) → \033[93m{self.state.output_model}\033[0m")

        if first_question != "":
            trimmed_first_question = first_question
            if len(first_question) > 100:
                words = split_text_into_words(first_question)
                trimmed_first_question = " ".join(words[:15]) + " (..)"

            print_text(state=self.state, text=f"{self.config.user_name}: {trimmed_first_question}")
            self.user_input.handle_full_sentence(first_question)
        else:
            await self.user_input.get_input()

        self.add_text_to_file(self.config.user_name, self.user_input.question_text)
        proceed, stop = self.pre_parse_question()
        self.reload_agent(force=proceed)
        if proceed:
            return False
        if stop:
            return True

        tries = 0
        while tries < self.config.retry_settings["max_tries"]:
            try:
                agent_response = self.agent.ask_question(self.user_input.question_text)
                if self.state.is_quiet:
                    print(agent_response)
                else:
                    print(f"{self.config.agent_name}: {agent_response}")

                if self.state.is_stopped:
                    break

                self.add_text_to_file(self.config.agent_name, agent_response)

                self.response.respond(agent_response)

                self.response.wait_for_audio_process()

                self.user_input.question_text = ""
                break
            except Exception as e:
                tb = traceback.format_exc()
                print_text(state=self.state, text=tb)
                sleep_sec = self.config.retry_settings["sleep_seconds_between_tries"]
                print_text(state=self.state, text=f"Error processing LLM: {e}")
                print_text(state=self.state, text=f"Sleep and try again after: {sleep_sec} sec")
                tries += 1
                time.sleep(sleep_sec)
