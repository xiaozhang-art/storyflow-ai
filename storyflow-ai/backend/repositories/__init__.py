from repositories.story_repo import (
    create_story,
    get_story,
    list_stories,
    update_story_status,
)
from repositories.task_repo import (
    create_task,
    get_task,
    get_task_by_story,
    update_task_progress,
)

# Backward-compatible module aliases used by other modules
class _StoryRepo:
    create_story = staticmethod(create_story)
    get_story = staticmethod(get_story)
    list_stories = staticmethod(list_stories)
    update_story_status = staticmethod(update_story_status)


class _TaskRepo:
    create_task = staticmethod(create_task)
    get_task = staticmethod(get_task)
    get_task_by_story = staticmethod(get_task_by_story)
    update_task_progress = staticmethod(update_task_progress)


story_repo = _StoryRepo()
task_repo = _TaskRepo()