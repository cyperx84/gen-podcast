"""Tests for runner.py: foreground execution, background spawning, and helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gen_podcast import runner as mod
from gen_podcast import status as status_mod


@pytest.fixture(autouse=True)
def tmp_jobs_dir(tmp_path, monkeypatch):
    """Redirect JOBS_DIR in both status and runner modules."""
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(status_mod, "JOBS_DIR", jobs)
    monkeypatch.setattr(mod, "JOBS_DIR", jobs)
    return jobs


@pytest.fixture
def tmp_output_dir(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(mod, "OUTPUT_DIR", out)
    return out


class TestBuildConfigDict:
    def test_builds_full_dict(self):
        result = mod._build_config_dict(
            content_source="/path/to/file.txt",
            briefing="discuss AI",
            episode_profile_name="casual_duo",
            speaker_profile_name="hosts",
            name="ep1",
            model_overrides={"outline_model": "gpt-4"},
        )
        assert result == {
            "content_source": "/path/to/file.txt",
            "briefing": "discuss AI",
            "episode_profile": "casual_duo",
            "speaker_profile": "hosts",
            "name": "ep1",
            "model_overrides": {"outline_model": "gpt-4"},
        }

    def test_none_model_overrides_becomes_empty_dict(self):
        result = mod._build_config_dict(
            content_source="<inline>",
            briefing=None,
            episode_profile_name="casual_duo",
            speaker_profile_name=None,
            name=None,
            model_overrides=None,
        )
        assert result["model_overrides"] == {}
        assert result["briefing"] is None
        assert result["speaker_profile"] is None


class TestIsJobDone:
    def test_missing_job(self, tmp_jobs_dir):
        assert mod.is_job_done("ghost") is False

    def test_queued_is_not_done(self, tmp_jobs_dir):
        status_mod.create_job("j1", {})
        assert mod.is_job_done("j1") is False

    def test_running_is_not_done(self, tmp_jobs_dir):
        status_mod.create_job("j1", {})
        status_mod.update_job("j1", status="running")
        assert mod.is_job_done("j1") is False

    def test_completed_is_done(self, tmp_jobs_dir):
        status_mod.create_job("j1", {})
        status_mod.update_job("j1", status="completed")
        assert mod.is_job_done("j1") is True

    def test_failed_is_done(self, tmp_jobs_dir):
        status_mod.create_job("j1", {})
        status_mod.update_job("j1", status="failed")
        assert mod.is_job_done("j1") is True


class TestRunForegroundHappyPath:
    """Tests that exercise run_foreground with podcast_creator stubbed out."""

    @pytest.fixture
    def stub_podcast_creator(self, monkeypatch):
        """Patch podcast_creator.configure and create_podcast."""
        configure_mock = MagicMock()

        async def fake_create_podcast(**kwargs):
            return {
                "final_output_file_path": "/tmp/out.mp3",
                "transcript": {"segments": ["hello"]},
                "outline": {"topics": ["intro"]},
            }

        monkeypatch.setattr("podcast_creator.configure", configure_mock)
        monkeypatch.setattr("podcast_creator.create_podcast", fake_create_podcast)
        return {"configure": configure_mock, "create_podcast": fake_create_podcast}

    def test_happy_path_completes(self, tmp_jobs_dir, tmp_output_dir, stub_podcast_creator, monkeypatch):
        status_mod.create_job("j1", {})

        # Make profile loading return simple dicts so override merging runs.
        episode = {
            "outline_provider": "openai",
            "outline_model": "gpt-4",
            "transcript_provider": "openai",
            "transcript_model": "gpt-4",
            "speaker_config": "hosts",
            "default_briefing": "episode default briefing",
        }
        speaker = {"tts_provider": "openai", "tts_model": "tts-1"}
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: episode)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: speaker)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        result = asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="some content",
                briefing=None,
                episode_profile_name="casual_duo",
                speaker_profile_name=None,
                name="my episode",
                model_overrides=None,
                output_dir=None,
                timeout=60,
            )
        )

        assert result["status"] == "completed"
        assert result["output"]["audio_file"] == "/tmp/out.mp3"
        assert result["output"]["transcript"] == {"segments": ["hello"]}
        assert result["output"]["outline"] == {"topics": ["intro"]}
        assert result["output"]["output_dir"].endswith("j1")

        # configure called twice: once for episode_config, once for speakers_config
        assert stub_podcast_creator["configure"].call_count == 2

    def test_speaker_profile_override_takes_precedence(
        self, tmp_jobs_dir, tmp_output_dir, stub_podcast_creator, monkeypatch
    ):
        status_mod.create_job("j1", {})
        episode = {"speaker_config": "default_speaker"}
        loaded_speakers: list[str] = []

        def fake_load_speaker(name):
            loaded_speakers.append(name)
            return {"tts_provider": "openai"}

        monkeypatch.setattr(mod, "load_episode_profile", lambda n: episode)
        monkeypatch.setattr(mod, "load_speaker_profile", fake_load_speaker)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="ep",
                speaker_profile_name="explicit_speaker",
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=60,
            )
        )

        # explicit speaker_profile should be used, not episode.speaker_config
        assert loaded_speakers == ["explicit_speaker"]

    def test_model_overrides_applied(
        self, tmp_jobs_dir, tmp_output_dir, stub_podcast_creator, monkeypatch
    ):
        status_mod.create_job("j1", {})
        episode = {
            "outline_provider": "openai",
            "outline_model": "gpt-3.5",
            "transcript_provider": "openai",
            "transcript_model": "gpt-3.5",
        }
        speaker = {"tts_provider": "openai", "tts_model": "tts-1"}
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: episode)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: speaker)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        overrides = {
            "outline_provider": "anthropic",
            "outline_model": "claude-3",
            "transcript_provider": "anthropic",
            "transcript_model": "claude-3",
            "tts_provider": "elevenlabs",
            "tts_model": "eleven_v2",
        }

        asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="ep",
                speaker_profile_name="sp",
                name=None,
                model_overrides=overrides,
                output_dir=None,
                timeout=60,
            )
        )

        # Profile dicts are mutated in place by run_foreground.
        assert episode["outline_provider"] == "anthropic"
        assert episode["outline_model"] == "claude-3"
        assert episode["transcript_provider"] == "anthropic"
        assert episode["transcript_model"] == "claude-3"
        assert speaker["tts_provider"] == "elevenlabs"
        assert speaker["tts_model"] == "eleven_v2"

    def test_explicit_briefing_beats_episode_default(
        self, tmp_jobs_dir, tmp_output_dir, monkeypatch
    ):
        status_mod.create_job("j1", {})
        received_briefing: dict = {}

        async def fake_create_podcast(**kwargs):
            received_briefing["value"] = kwargs["briefing"]
            return {"final_output_file_path": "/tmp/out.mp3", "transcript": None, "outline": None}

        monkeypatch.setattr("podcast_creator.configure", MagicMock())
        monkeypatch.setattr("podcast_creator.create_podcast", fake_create_podcast)
        monkeypatch.setattr(
            mod, "load_episode_profile", lambda n: {"default_briefing": "episode default"}
        )
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing="explicit!",
                episode_profile_name="ep",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=60,
            )
        )
        assert received_briefing["value"] == "explicit!"

    def test_episode_default_briefing_used_when_no_explicit(
        self, tmp_jobs_dir, tmp_output_dir, monkeypatch
    ):
        status_mod.create_job("j1", {})
        received: dict = {}

        async def fake_create_podcast(**kwargs):
            received["value"] = kwargs["briefing"]
            return {"final_output_file_path": "/tmp/out.mp3", "transcript": None, "outline": None}

        monkeypatch.setattr("podcast_creator.configure", MagicMock())
        monkeypatch.setattr("podcast_creator.create_podcast", fake_create_podcast)
        monkeypatch.setattr(
            mod, "load_episode_profile", lambda n: {"default_briefing": "ep default"}
        )
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="ep",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=60,
            )
        )
        assert received["value"] == "ep default"

    def test_generic_briefing_fallback(self, tmp_jobs_dir, tmp_output_dir, monkeypatch):
        status_mod.create_job("j1", {})
        received: dict = {}

        async def fake_create_podcast(**kwargs):
            received["value"] = kwargs["briefing"]
            return {"final_output_file_path": "/tmp/out.mp3", "transcript": None, "outline": None}

        monkeypatch.setattr("podcast_creator.configure", MagicMock())
        monkeypatch.setattr("podcast_creator.create_podcast", fake_create_podcast)
        # No episode profile at all (builtin name, returns None)
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: None)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="tech_discussion",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=60,
            )
        )
        assert "engaging podcast" in received["value"]

    def test_custom_output_dir(self, tmp_jobs_dir, tmp_path, stub_podcast_creator, monkeypatch):
        status_mod.create_job("j1", {})
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: None)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        custom_out = tmp_path / "my_custom_dir"

        result = asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="tech_discussion",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=str(custom_out),
                timeout=60,
            )
        )
        assert custom_out.exists()
        assert result["output"]["output_dir"] == str(custom_out)


class TestRunForegroundErrorPaths:
    def test_timeout_marks_failed(self, tmp_jobs_dir, tmp_output_dir, monkeypatch):
        status_mod.create_job("j1", {})

        async def slow(**kwargs):
            await asyncio.sleep(10)
            return {}

        monkeypatch.setattr("podcast_creator.configure", MagicMock())
        monkeypatch.setattr("podcast_creator.create_podcast", slow)
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: None)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        result = asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="tech_discussion",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=0.01,  # instant timeout
            )
        )
        assert result["status"] == "failed"
        assert "timed out" in result["error"].lower()
        assert result["completed_at"] is not None

    def test_exception_marks_failed_with_traceback(
        self, tmp_jobs_dir, tmp_output_dir, monkeypatch
    ):
        status_mod.create_job("j1", {})

        async def boom(**kwargs):
            raise RuntimeError("kaboom")

        monkeypatch.setattr("podcast_creator.configure", MagicMock())
        monkeypatch.setattr("podcast_creator.create_podcast", boom)
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: None)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        result = asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="tech_discussion",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=60,
            )
        )
        assert result["status"] == "failed"
        assert "RuntimeError" in result["error"]
        assert "kaboom" in result["error"]

    def test_no_timeout_when_none(self, tmp_jobs_dir, tmp_output_dir, monkeypatch):
        """timeout=None should bypass asyncio.wait_for."""
        status_mod.create_job("j1", {})
        called_wait_for = MagicMock()

        async def fake_create_podcast(**kwargs):
            return {"final_output_file_path": "/x.mp3", "transcript": None, "outline": None}

        monkeypatch.setattr("podcast_creator.configure", MagicMock())
        monkeypatch.setattr("podcast_creator.create_podcast", fake_create_podcast)
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: None)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)
        monkeypatch.setattr(mod.asyncio, "wait_for", called_wait_for)

        result = asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="tech_discussion",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=None,
            )
        )
        assert result["status"] == "completed"
        called_wait_for.assert_not_called()


class TestToJsonSafe:
    """Exercise the nested _to_json_safe helper via run_foreground outputs."""

    def test_plain_objects_use_dunder_dict(self, tmp_jobs_dir, tmp_output_dir, monkeypatch):
        """Objects without model_dump but with __dict__ should be serialized via __dict__."""
        status_mod.create_job("j1", {})

        class PlainObj:
            def __init__(self):
                self.topic = "intro"
                self.score = 7

        async def fake_create_podcast(**kwargs):
            return {
                "final_output_file_path": "/x.mp3",
                "transcript": None,
                "outline": PlainObj(),
            }

        monkeypatch.setattr("podcast_creator.configure", MagicMock())
        monkeypatch.setattr("podcast_creator.create_podcast", fake_create_podcast)
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: None)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        result = asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="tech_discussion",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=60,
            )
        )
        assert result["output"]["outline"] == {"topic": "intro", "score": 7}

    def test_model_dump_objects_serialized(self, tmp_jobs_dir, tmp_output_dir, monkeypatch):
        status_mod.create_job("j1", {})

        class FakeModel:
            def model_dump(self):
                return {"a": 1, "b": [2, 3]}

        async def fake_create_podcast(**kwargs):
            return {
                "final_output_file_path": "/x.mp3",
                "transcript": FakeModel(),
                "outline": [FakeModel(), {"nested": FakeModel()}],
            }

        monkeypatch.setattr("podcast_creator.configure", MagicMock())
        monkeypatch.setattr("podcast_creator.create_podcast", fake_create_podcast)
        monkeypatch.setattr(mod, "load_episode_profile", lambda n: None)
        monkeypatch.setattr(mod, "load_speaker_profile", lambda n: None)
        monkeypatch.setattr(mod, "inject_api_keys", lambda e, s: None)

        result = asyncio.run(
            mod.run_foreground(
                job_id="j1",
                content="content",
                briefing=None,
                episode_profile_name="tech_discussion",
                speaker_profile_name=None,
                name=None,
                model_overrides=None,
                output_dir=None,
                timeout=60,
            )
        )
        assert result["output"]["transcript"] == {"a": 1, "b": [2, 3]}
        assert result["output"]["outline"][0] == {"a": 1, "b": [2, 3]}
        assert result["output"]["outline"][1]["nested"] == {"a": 1, "b": [2, 3]}


class TestSpawnBackground:
    """Test argv construction and Popen invocation, without actually spawning."""

    @pytest.fixture
    def fake_popen(self, monkeypatch):
        proc = MagicMock()
        proc.pid = 4242
        popen_mock = MagicMock(return_value=proc)
        monkeypatch.setattr("subprocess.Popen", popen_mock)
        return popen_mock

    def test_inline_content_written_to_tempfile(self, tmp_jobs_dir, fake_popen):
        job_id = mod.spawn_background(
            content="inline content",
            content_file=None,
            briefing=None,
            episode_profile_name="casual_duo",
            speaker_profile_name=None,
            name=None,
        )
        # Temp content file should exist in JOBS_DIR
        content_file = tmp_jobs_dir / f"{job_id}.content"
        assert content_file.exists()
        assert content_file.read_text() == "inline content"

        # Popen called with --content-file pointing at that temp
        cmd = fake_popen.call_args.args[0]
        assert "--content-file" in cmd
        idx = cmd.index("--content-file")
        assert cmd[idx + 1] == str(content_file)

    def test_explicit_content_file_used_directly(self, tmp_jobs_dir, tmp_path, fake_popen):
        real_file = tmp_path / "article.txt"
        real_file.write_text("article body")

        job_id = mod.spawn_background(
            content=None,
            content_file=str(real_file),
            briefing=None,
            episode_profile_name="casual_duo",
            speaker_profile_name=None,
            name=None,
        )
        cmd = fake_popen.call_args.args[0]
        assert "--content-file" in cmd
        idx = cmd.index("--content-file")
        assert cmd[idx + 1] == str(real_file)
        # No temp file created in this case
        assert not (tmp_jobs_dir / f"{job_id}.content").exists()

    def test_all_flags_passed_through(self, tmp_jobs_dir, fake_popen):
        job_id = mod.spawn_background(
            content="hi",
            content_file=None,
            briefing="brief",
            episode_profile_name="casual_duo",
            speaker_profile_name="hosts",
            name="my ep",
            model_overrides={
                "outline_provider": "openai",
                "outline_model": "gpt-4",
                "tts_provider": "elevenlabs",
            },
            output_dir="/tmp/custom",
            timeout=120,
        )
        cmd = fake_popen.call_args.args[0]

        assert "--briefing" in cmd
        assert cmd[cmd.index("--briefing") + 1] == "brief"

        assert "--episode-profile" in cmd
        assert cmd[cmd.index("--episode-profile") + 1] == "casual_duo"

        assert "--speaker-profile" in cmd
        assert cmd[cmd.index("--speaker-profile") + 1] == "hosts"

        assert "--name" in cmd
        assert cmd[cmd.index("--name") + 1] == "my ep"

        assert "--output-dir" in cmd
        assert cmd[cmd.index("--output-dir") + 1] == "/tmp/custom"

        assert "--timeout" in cmd
        assert cmd[cmd.index("--timeout") + 1] == "120"

        # underscore → dash conversion for overrides
        assert "--outline-provider" in cmd
        assert cmd[cmd.index("--outline-provider") + 1] == "openai"
        assert "--outline-model" in cmd
        assert cmd[cmd.index("--outline-model") + 1] == "gpt-4"
        assert "--tts-provider" in cmd
        assert cmd[cmd.index("--tts-provider") + 1] == "elevenlabs"

        assert "--foreground" in cmd
        assert "--job-id" in cmd
        assert cmd[cmd.index("--job-id") + 1] == job_id

    def test_job_created_in_queued_state(self, tmp_jobs_dir, fake_popen):
        job_id = mod.spawn_background(
            content="hi",
            content_file=None,
            briefing=None,
            episode_profile_name="casual_duo",
            speaker_profile_name=None,
            name=None,
        )
        job = status_mod.read_job(job_id)
        assert job is not None
        assert job.status == "queued"
        assert job.pid == 4242  # from fake_popen fixture
        assert job.config["episode_profile"] == "casual_duo"

    def test_log_file_created(self, tmp_jobs_dir, fake_popen):
        job_id = mod.spawn_background(
            content="hi",
            content_file=None,
            briefing=None,
            episode_profile_name="casual_duo",
            speaker_profile_name=None,
            name=None,
        )
        assert (tmp_jobs_dir / f"{job_id}.log").exists()

    def test_popen_detached_session(self, tmp_jobs_dir, fake_popen):
        mod.spawn_background(
            content="hi",
            content_file=None,
            briefing=None,
            episode_profile_name="casual_duo",
            speaker_profile_name=None,
            name=None,
        )
        kwargs = fake_popen.call_args.kwargs
        assert kwargs.get("start_new_session") is True
        # stdout redirected (not inheriting parent's)
        assert kwargs.get("stdout") is not None
