from __future__ import annotations

import json
import sys
from pathlib import Path

from plural import ScriptedPolicy, TaskData
from plural.environments import verify_replay
from plural.tracing import ParsedAction
from plural.types import ChatRequest

_TWITTER = Path(__file__).resolve().parents[2] / "examples" / "environment" / "twitter"
sys.path.insert(0, str(_TWITTER))
sys.modules.pop("env", None)
from env import TwitterEnv, make_env  # noqa: E402

sys.modules.pop("env", None)
sys.path.remove(str(_TWITTER))


def _env(seed: int = 42, goal: str = "reply_to_mentions") -> TwitterEnv:
    env = TwitterEnv()
    env.setup(
        TaskData(
            task_id="t",
            input="act",
            metadata={"seed": seed, "account": "agent", "goal": goal},
        )
    )
    return env


def test_reset_is_deterministic() -> None:
    a = _env(42)
    b = _env(42)
    assert a.snapshot()["mentions"] == b.snapshot()["mentions"]
    assert list(a.state.posts) == list(b.state.posts)


def test_tweet_like_follow_reply() -> None:
    env = _env()
    posted = env.tweet("hello from the sim")
    post_id = posted["post"]["post_id"]
    assert posted["post"]["author"] == "agent"

    liked = env.like(post_id)
    assert liked["likes"] == 1
    env.unlike(post_id)
    assert env.posts[post_id].likes == set()

    followed = env.follow("alice")
    assert followed["following"] == "alice"
    assert "alice" in env.users["agent"].following
    env.unfollow("alice")
    assert "alice" not in env.users["agent"].following

    mention = env._mentions()[0]
    reply = env.reply(mention.post_id, "on it")
    assert reply["post"]["reply_to"] == mention.post_id


def test_quote_repost_bookmark_media() -> None:
    env = _env()
    timeline = env.view_timeline()["posts"]
    target = timeline[0]["post_id"]
    env.repost(target)
    quoted = env.quote(target, "adding context")
    assert quoted["post"]["quote_of"] == target
    env.bookmark(target)
    image = env.create_image("sunset")
    video = env.create_video("walkthrough")
    tweeted = env.tweet("media", media_ids=[image["media_id"]])
    assert tweeted["post"]["media"][0]["type"] == "image"
    assert video["type"] == "video"


def test_goal_scores() -> None:
    env = _env(goal="reply_to_mentions")
    assert env.score("reply_to_mentions") < 1.0
    for mention in env._mentions():
        env.reply(mention.post_id, "ack")
    assert env.score("reply_to_mentions") == 1.0
    assert env.done() is True

    likes_env = _env(goal="get_n_likes")
    likes_env.tweet("please like")
    result = likes_env.wait_for_engagement()
    assert result == {"new_likes": 3, "likes_on_own_posts": 3}
    assert likes_env.score("get_n_likes") == 1.0
    assert likes_env.done() is True

    empty_env = _env(goal="get_n_likes")
    empty_env.tweet("   ")
    assert empty_env.wait_for_engagement()["new_likes"] == 0


def test_make_env_registers_tools() -> None:
    env = make_env()
    assert env.name == "twitter-account"
    assert env.version == "0.2.0"
    names = {t.function.name for t in env.tool_defs}
    for required in {
        "view_timeline",
        "view_profile",
        "view_post",
        "view_notifications",
        "follow",
        "unfollow",
        "tweet",
        "wait_for_engagement",
        "reply",
        "like",
        "unlike",
        "repost",
        "quote",
        "bookmark",
        "create_image",
        "create_video",
    }:
        assert required in names
    tasks = list(env.iter_tasks())
    assert tasks[0].metadata["goal"] == "reply_to_mentions"


class _ReplyPolicy:
    def __init__(self) -> None:
        self.ids: list[str] | None = None
        self.index = 0

    def act(self, request: ChatRequest, **_: object) -> ParsedAction:
        if self.ids is None:
            for message in reversed(request.messages):
                if message.name == "view_notifications" and message.content:
                    payload = json.loads(message.content)
                    self.ids = [str(item["post_id"]) for item in payload["mentions"]]
                    break
            if self.ids is None:
                return ParsedAction(name="view_notifications")
        post_id = self.ids[self.index]
        self.index += 1
        return ParsedAction(name="reply", arguments={"post_id": post_id, "text": "Thanks!"})


def test_reply_goal_run_episode_records_actions() -> None:
    env = make_env()
    task = list(env.iter_tasks())[0]
    rollout = env.run_episode(task, _ReplyPolicy())

    actions = [
        action.name for decision in rollout.trace.decisions() for action in decision.parsed_action
    ]
    assert actions == ["view_notifications", "reply", "reply"]
    assert rollout.trace.terminated is True
    assert rollout.trace.outcome is not None
    assert rollout.trace.outcome.reward == 1.0


def test_likes_goal_step_and_replay() -> None:
    env = make_env()
    task = list(env.iter_tasks())[1]
    env.reset(task)
    first = env.step(ParsedAction(name="tweet", arguments={"text": "A useful update"}))
    second = env.step(ParsedAction(name="wait_for_engagement"))
    rollout = env.close_episode()

    assert first.terminated is False
    assert second.terminated is True
    assert second.observation.followers == 3
    assert env.score() == 1.0
    actions = [
        action.name for decision in rollout.trace.decisions() for action in decision.parsed_action
    ]
    assert actions == ["tweet", "wait_for_engagement"]
    replay = verify_replay(make_env(), rollout.trace)
    assert replay.ok, replay.mismatches


def test_likes_goal_run_episode() -> None:
    env = make_env()
    task = list(env.iter_tasks())[1]
    rollout = env.run_episode(
        task,
        ScriptedPolicy(
            [
                ParsedAction(name="tweet", arguments={"text": "A useful update"}),
                ParsedAction(name="wait_for_engagement"),
            ]
        ),
    )

    assert rollout.trace.terminated is True
    assert rollout.trace.outcome is not None
    assert rollout.trace.outcome.reward == 1.0
