"""
GitHub Memory Layer for MEDDICC Agent

Manages learnings, versions, diffs, and counter files via GitHub API.
Supports both local file operations and GitHub API for Actions environment.
"""
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import base64


# Detect if running in GitHub Actions
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # Format: "owner/repo"


class GitHubMemory:
    """Manages memory layer files (learnings, versions, diffs, counter)."""

    def __init__(self, repo_root: Path = None):
        """Initialize memory manager."""
        if repo_root is None:
            repo_root = Path(__file__).parent.parent

        self.repo_root = Path(repo_root)
        self.memory_dir = self.repo_root / "memory"
        self.learnings_dir = self.memory_dir / "learnings"
        self.versions_dir = self.memory_dir / "versions"
        self.diffs_dir = self.memory_dir / "diffs"
        self.issues_dir = self.memory_dir / "issues"
        self.rubric_obs_dir = self.memory_dir / "rubric_observations"
        self.meta_dir = self.memory_dir / "meta"
        self.calls_dir = self.memory_dir / "calls"

        # Ensure directories exist (both local and GitHub Actions)
        self.learnings_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.diffs_dir.mkdir(parents=True, exist_ok=True)
        self.issues_dir.mkdir(parents=True, exist_ok=True)
        self.rubric_obs_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.calls_dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────
    # Counter Management
    # ─────────────────────────────────────────────────────────────────

    def get_counter(self) -> dict:
        """Get current counter state."""
        counter_path = self.meta_dir / "counter.json"

        if counter_path.exists():
            with open(counter_path, 'r') as f:
                return json.load(f)

        # Initialize if doesn't exist
        today = datetime.now().strftime('%Y-%m-%d')
        next_rewrite = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')

        return {
            "total_runs": 0,
            "runs_since_rewrite": 0,
            "last_full_rewrite": None,
            "next_full_rewrite_due": next_rewrite
        }

    def update_counter(self, is_full_rewrite: bool = False) -> dict:
        """Increment counter and optionally reset for full rewrite."""
        counter = self.get_counter()

        counter["total_runs"] += 1

        if is_full_rewrite:
            counter["runs_since_rewrite"] = 0
            counter["last_full_rewrite"] = datetime.now().strftime('%Y-%m-%d')
            counter["next_full_rewrite_due"] = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        else:
            counter["runs_since_rewrite"] += 1

        # Write back
        counter_path = self.meta_dir / "counter.json"
        with open(counter_path, 'w') as f:
            json.dump(counter, f, indent=2)

        return counter

    def should_full_rewrite(self) -> bool:
        """Check if it's time for a full rewrite (30 days)."""
        counter = self.get_counter()
        return counter["runs_since_rewrite"] >= 30

    # ─────────────────────────────────────────────────────────────────
    # Learning Entries
    # ─────────────────────────────────────────────────────────────────

    def save_learning(self, learning: dict) -> Path:
        """Save a learning entry."""
        # Generate ID
        today = datetime.now().strftime('%Y-%m-%d')
        counter = self.get_counter()
        run_num = counter["runs_since_rewrite"] + 1
        learning_id = f"{today}_{run_num:03d}"

        learning["id"] = learning_id
        learning["timestamp"] = datetime.now().isoformat()

        # Write file
        learning_path = self.learnings_dir / f"{learning_id}.json"
        with open(learning_path, 'w') as f:
            json.dump(learning, f, indent=2)

        return learning_path

    def save_issue(self, issue: dict) -> Path:
        """Save an issue entry (bugs, prompt_issue outcomes)."""
        # Generate ID (same format as learning entries)
        today = datetime.now().strftime('%Y-%m-%d')
        counter = self.get_counter()
        run_num = counter["runs_since_rewrite"] + 1
        issue_id = f"{today}_{run_num:03d}"

        issue["id"] = issue_id
        issue["timestamp"] = datetime.now().isoformat()

        # Write file to issues directory
        issue_path = self.issues_dir / f"{issue_id}.json"
        with open(issue_path, 'w') as f:
            json.dump(issue, f, indent=2)

        return issue_path

    def save_rubric_observation(self, observation: dict,
                                company: str) -> Optional[Path]:
        """
        Save a rubric observation only when criterion_fired is not null
        and suggested_change is not null.
        Observations with no criterion fired are not worth storing.
        """
        if not observation.get('criterion_fired'):
            return None
        if not observation.get('suggested_change'):
            return None

        today = datetime.now().strftime('%Y-%m-%d')
        existing = list(self.rubric_obs_dir.glob(f'{today}_*.json'))
        idx = str(len(existing) + 1).zfill(3)
        path = self.rubric_obs_dir / f'{today}_{idx}.json'

        data = {
            'id': f'{today}_{idx}',
            'timestamp': datetime.now().isoformat(),
            'company': company,
            **observation
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return path

    def get_todays_learnings(self) -> List[dict]:
        """Get all learning entries from today."""
        today = datetime.now().strftime('%Y-%m-%d')
        learnings = []

        for path in self.learnings_dir.glob(f"{today}_*.json"):
            with open(path, 'r') as f:
                learnings.append(json.load(f))

        return sorted(learnings, key=lambda x: x.get('id', ''))

    def get_recent_learnings(self, days: int = 30) -> List[dict]:
        """Get learning entries from last N days."""
        cutoff = datetime.now() - timedelta(days=days)
        learnings = []

        for path in self.learnings_dir.glob("*.json"):
            with open(path, 'r') as f:
                learning = json.load(f)
                timestamp = learning.get('timestamp', '')

                try:
                    learning_date = datetime.fromisoformat(timestamp)
                    if learning_date >= cutoff:
                        learnings.append(learning)
                except:
                    pass

        return sorted(learnings, key=lambda x: x.get('timestamp', ''))

    # ─────────────────────────────────────────────────────────────────
    # Versions & Diffs
    # ─────────────────────────────────────────────────────────────────

    def save_version(self, claude_md_content: str) -> Path:
        """Save a versioned snapshot of CLAUDE.md."""
        today = datetime.now().strftime('%Y-%m-%d')
        version_path = self.versions_dir / f"CLAUDE_{today}.md"

        with open(version_path, 'w') as f:
            f.write(claude_md_content)

        return version_path

    def save_diff(self, diff_content: str) -> Path:
        """Save daily diff explanation."""
        today = datetime.now().strftime('%Y-%m-%d')
        diff_path = self.diffs_dir / f"{today}.md"

        with open(diff_path, 'w') as f:
            f.write(diff_content)

        return diff_path

    def get_current_claude_md(self) -> str:
        """Get current CLAUDE.md content."""
        claude_md_path = self.repo_root / "prompts" / "CLAUDE.md"

        with open(claude_md_path, 'r') as f:
            return f.read()

    def update_claude_md(self, new_content: str) -> None:
        """Update CLAUDE.md file."""
        claude_md_path = self.repo_root / "prompts" / "CLAUDE.md"

        with open(claude_md_path, 'w') as f:
            f.write(new_content)

    # ─────────────────────────────────────────────────────────────────
    # GitHub PR Creation (for Actions environment)
    # ─────────────────────────────────────────────────────────────────

    def create_pr(
        self,
        branch_name: str,
        title: str,
        body: str,
        files_to_commit: Dict[str, str]
    ) -> Optional[str]:
        """
        Create a GitHub PR with file changes.

        Args:
            branch_name: Name of the branch
            title: PR title
            body: PR description
            files_to_commit: Dict of {file_path: content}

        Returns:
            PR URL if successful, None otherwise
        """
        if not IS_GITHUB_ACTIONS:
            print("⚠️  PR creation only works in GitHub Actions environment")
            return None

        if not GITHUB_TOKEN or not GITHUB_REPO:
            print("⚠️  Missing GITHUB_TOKEN or GITHUB_REPO")
            return None

        try:
            import requests

            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            api_base = f"https://api.github.com/repos/{GITHUB_REPO}"

            # 1. Get default branch SHA
            repo_resp = requests.get(f"{api_base}", headers=headers)
            repo_resp.raise_for_status()
            default_branch = repo_resp.json()["default_branch"]

            # 2. Get default branch ref
            ref_resp = requests.get(f"{api_base}/git/ref/heads/{default_branch}", headers=headers)
            ref_resp.raise_for_status()
            base_sha = ref_resp.json()["object"]["sha"]

            # 3. Create new branch
            create_ref_resp = requests.post(
                f"{api_base}/git/refs",
                headers=headers,
                json={
                    "ref": f"refs/heads/{branch_name}",
                    "sha": base_sha
                }
            )
            create_ref_resp.raise_for_status()

            # 4. Create/update files on new branch
            for file_path, content in files_to_commit.items():
                # Get current file SHA if it exists
                try:
                    file_resp = requests.get(f"{api_base}/contents/{file_path}", headers=headers)
                    file_sha = file_resp.json()["sha"] if file_resp.status_code == 200 else None
                except:
                    file_sha = None

                # Update file
                content_b64 = base64.b64encode(content.encode()).decode()
                update_data = {
                    "message": f"Update {file_path}",
                    "content": content_b64,
                    "branch": branch_name
                }
                if file_sha:
                    update_data["sha"] = file_sha

                update_resp = requests.put(
                    f"{api_base}/contents/{file_path}",
                    headers=headers,
                    json=update_data
                )
                update_resp.raise_for_status()

            # 5. Create PR
            pr_resp = requests.post(
                f"{api_base}/pulls",
                headers=headers,
                json={
                    "title": title,
                    "body": body,
                    "head": branch_name,
                    "base": default_branch
                }
            )
            pr_resp.raise_for_status()

            pr_url = pr_resp.json()["html_url"]
            return pr_url

        except Exception as e:
            print(f"Error creating PR: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────
    # Call Cache Management
    # ─────────────────────────────────────────────────────────────────

    def load_call_cache(self, slug: str) -> Optional[dict]:
        """Load call cache for a company slug."""
        cache_path = self.calls_dir / f"{slug}.json"
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"   ⚠️  Error loading cache {slug}.json: {e}")
            return None

    def save_call_cache(self, slug: str, cache_data: dict):
        """Save call cache for a company slug."""
        cache_path = self.calls_dir / f"{slug}.json"
        cache_data['last_etl_date'] = datetime.now().isoformat()

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️  Error saving cache {slug}.json: {e}")

    def load_deal_index(self) -> dict:
        """Load deal index mapping deal_id -> company_slug."""
        index_path = self.calls_dir / "_deal_index.json"
        if not index_path.exists():
            return {}

        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"   ⚠️  Error loading deal index: {e}")
            return {}

    def save_deal_index(self, index: dict):
        """Save deal index mapping deal_id -> company_slug."""
        index_path = self.calls_dir / "_deal_index.json"

        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️  Error saving deal index: {e}")


def get_memory_manager(repo_root: Path = None) -> GitHubMemory:
    """Get configured memory manager."""
    return GitHubMemory(repo_root)


if __name__ == "__main__":
    # Test memory operations
    memory = get_memory_manager()

    print("=" * 80)
    print("TESTING MEMORY LAYER")
    print("=" * 80)

    # Test counter
    counter = memory.get_counter()
    print(f"\nCounter state:")
    print(json.dumps(counter, indent=2))

    # Test learning save
    test_learning = {
        "company": "Test Corp",
        "deal_id": "123456",
        "loop_performance": {
            "iterations_to_pass": 2,
            "passed": True,
            "budget_exhausted": False
        },
        "cumulative_calls_context": 3,
        "iteration_1_failures": ["Evidence quality"],
        "components_weak": ["Champion"],
        "components_strong": ["Metrics", "Economic Buyer"],
        "required_changes_injected": "Added specific evidence for Economic Buyer",
        "resolution": "Passed on iteration 2",
        "proposed_instruction": "Always quote specific evidence from calls, not generic statements"
    }

    learning_path = memory.save_learning(test_learning)
    print(f"\n✓ Saved learning to: {learning_path}")

    # Test version save
    test_claude_md = "# Test CLAUDE.md\n\nThis is a test version."
    version_path = memory.save_version(test_claude_md)
    print(f"✓ Saved version to: {version_path}")

    # Test diff save
    test_diff = "# Daily Diff - 2026-07-29\n\nAdded 3 new learnings about evidence quality."
    diff_path = memory.save_diff(test_diff)
    print(f"✓ Saved diff to: {diff_path}")

    # Check if should do full rewrite
    should_rewrite = memory.should_full_rewrite()
    print(f"\nShould do full rewrite: {should_rewrite}")

    print("\n" + "=" * 80)
    print("✓ Memory layer test complete")
    print("=" * 80)
