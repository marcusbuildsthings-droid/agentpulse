"""Tests for @agent, @task, @trace decorators."""

import asyncio

from agentpulse.decorators import agent, task, trace


def test_trace_decorator_sync():
    @trace
    def my_func(x):
        return x * 2

    result = my_func(5)
    assert result == 10
    assert my_func.__name__ == "my_func"


def test_task_decorator_sync():
    @task(name="multiply")
    def my_task(x):
        return x * 3

    result = my_task(4)
    assert result == 12


def test_agent_decorator_on_class():
    @agent(name="test-agent")
    class MyAgent:
        def run(self):
            return "done"

    a = MyAgent()
    assert a.run() == "done"
    assert hasattr(a, "_agentpulse_span")


def test_trace_decorator_async():
    @trace
    async def async_func(x):
        return x + 1

    result = asyncio.run(async_func(10))
    assert result == 11


def test_decorator_preserves_exceptions():
    @task
    def failing():
        raise ValueError("oops")

    try:
        failing()
        assert False, "Should have raised"
    except ValueError as e:
        assert str(e) == "oops"


def test_nested_decorators():
    @agent
    def outer():
        @task
        def inner():
            return 42
        return inner()

    assert outer() == 42
