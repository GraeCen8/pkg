"""Interactive package search with fzf and curses fallback."""

from __future__ import annotations

import curses
import shutil
import subprocess


def _has_fzf() -> bool:
    """Return True if fzf is available."""
    return shutil.which("fzf") is not None


def fzf_search(
    packages: list[str],
    query: str = "",
    preview_cmd: str = "",
) -> str | None:
    """Run fzf with a list of packages and return selected item.

    Args:
        packages: List of package names to search.
        query: Optional pre-filter query.
        preview_cmd: Command to run for preview (use {1} as placeholder).

    Returns:
        Selected package name or None if cancelled.
    """
    if not packages:
        return None

    cmd = [
        "fzf",
        "--prompt",
        "pkg> ",
        "--height",
        "40%",
        "--reverse",
        "--no-multi",
        "--bind",
        "alt-p:toggle-preview",
        "--color",
        "pointer:green,marker:green",
    ]

    if preview_cmd:
        cmd.extend(
            [
                "--preview",
                preview_cmd,
                "--preview-window",
                "down:60%:wrap",
            ]
        )

    if query:
        cmd.extend(["--query", query])

    proc = subprocess.run(
        cmd,
        input="\n".join(packages),
        capture_output=True,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def fallback_search(
    packages: list[str],
    query: str = "",
    preview_fn=None,
) -> str | None:
    """Curses-based arrow-key search as fallback when fzf is not installed.

    Args:
        packages: List of package names to search.
        query: Optional pre-filter query.
        preview_fn: Optional callable(pkg_name) -> str for preview.

    Returns:
        Selected package name or None if cancelled.
    """
    if not packages:
        return None

    filtered = packages
    if query:
        q = query.lower()
        filtered = [p for p in packages if q in p.lower()]

    if not filtered:
        return None

    return curses.wrapper(_curses_search, filtered, preview_fn)


def _curses_search(stdscr, packages: list[str], preview_fn=None) -> str | None:
    """Core curses search loop."""
    curses.curs_set(0)
    curses.use_default_colors()

    # Init colors
    curses.init_pair(1, curses.COLOR_GREEN, -1)  # selected
    curses.init_pair(2, curses.COLOR_CYAN, -1)  # title
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # status

    selected = 0
    scroll = 0
    query = ""
    mode = "search"  # search or action
    action_choice = 0
    actions = ["add", "remove", "print"]
    preview_text = ""

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        if mode == "search":
            # Title
            title = " pkg search "
            stdscr.addnstr(0, 0, title, width, curses.color_pair(2) | curses.A_BOLD)

            # Search box
            search_line = f" > {query}_"
            stdscr.addnstr(1, 0, search_line, width)

            # Package list
            list_height = height - 4
            max_packages = min(len(packages), list_height)

            # Adjust scroll
            if selected < scroll:
                scroll = selected
            elif selected >= scroll + list_height:
                scroll = selected - list_height + 1

            for i in range(max_packages):
                idx = i + scroll
                if idx >= len(packages):
                    break

                pkg = packages[idx]
                y = i + 2

                # Truncate to fit
                display = pkg[: width - 2]

                if idx == selected:
                    stdscr.addnstr(
                        y, 0, f" > {display}", width, curses.color_pair(1) | curses.A_BOLD
                    )
                else:
                    stdscr.addnstr(y, 0, f"   {display}", width)

            # Preview pane (right side)
            if preview_fn and preview_text:
                preview_x = width // 2 + 2
                preview_width = width // 2 - 2
                if preview_width > 10:
                    stdscr.addnstr(
                        0,
                        preview_x,
                        " preview ",
                        preview_width,
                        curses.color_pair(2) | curses.A_BOLD,
                    )
                    for j, line in enumerate(preview_text.splitlines()[: list_height - 1]):
                        if j + 2 < height:
                            stdscr.addnstr(j + 2, preview_x, line[:preview_width], preview_width)

            # Status bar
            status = f" {selected + 1}/{len(packages)} "
            stdscr.addnstr(height - 1, 0, status, width, curses.color_pair(3))

        elif mode == "action":
            # Action menu
            pkg_name = packages[selected]
            stdscr.addnstr(0, 0, f" pkg: {pkg_name}", width, curses.color_pair(2) | curses.A_BOLD)
            stdscr.addnstr(1, 0, "", width)
            stdscr.addnstr(2, 0, " What would you like to do?", width, curses.A_BOLD)

            for i, action in enumerate(actions):
                y = 3 + i
                label = f"  {i + 1}: {action}"
                if i == action_choice:
                    stdscr.addnstr(y, 0, f" >{label}", width, curses.color_pair(1) | curses.A_BOLD)
                else:
                    stdscr.addnstr(y, 0, label, width)

            # Show preview if available
            if preview_fn and preview_text:
                preview_x = width // 2 + 2
                preview_width = width // 2 - 2
                if preview_width > 10:
                    for j, line in enumerate(preview_text.splitlines()[: height - 4]):
                        if j + 4 < height:
                            stdscr.addnstr(j + 4, preview_x, line[:preview_width], preview_width)

            # Help
            help_text = " Enter: select  Esc: back  1/2/3: quick select"
            if height > 5:
                stdscr.addnstr(height - 1, 0, help_text, width, curses.color_pair(3))

        stdscr.refresh()

        # Get input
        key = stdscr.getch()

        if mode == "search":
            if key == 27:  # Esc
                return None
            elif key == curses.KEY_UP:
                selected = max(0, selected - 1)
            elif key == curses.KEY_DOWN:
                selected = min(len(packages) - 1, selected + 1)
            elif key == 10:  # Enter
                mode = "action"
                action_choice = 0
                if preview_fn:
                    preview_text = preview_fn(packages[selected])
            elif key == 127 or key == curses.KEY_BACKSPACE:  # Backspace
                query = query[:-1]
                # Re-filter
                if query:
                    q = query.lower()
                    packages[:] = [p for p in packages if q in p.lower()]
                else:
                    packages[:] = packages  # Reset to original
                selected = 0
                scroll = 0
            elif 32 <= key <= 126:  # Printable char
                query += chr(key)
                # Re-filter
                q = query.lower()
                packages = [p for p in packages if q in p.lower()]
                selected = 0
                scroll = 0
            elif key == ord("1"):
                query = ""
                selected = 0
                scroll = 0
            elif key == ord("2"):
                query = ""
                selected = min(1, len(packages) - 1)
                scroll = 0
            elif key == ord("3"):
                query = ""
                selected = min(2, len(packages) - 1)
                scroll = 0

        elif mode == "action":
            if key == 27:  # Esc
                mode = "search"
                preview_text = ""
            elif key == curses.KEY_UP:
                action_choice = max(0, action_choice - 1)
            elif key == curses.KEY_DOWN:
                action_choice = min(len(actions) - 1, action_choice + 1)
            elif key == 10:  # Enter
                return f"{actions[action_choice]}:{packages[selected]}"
            elif key == ord("1"):
                return f"add:{packages[selected]}"
            elif key == ord("2"):
                return f"remove:{packages[selected]}"
            elif key == ord("3"):
                return f"print:{packages[selected]}"


def action_menu(pkg_name: str, preview_fn=None) -> str | None:
    """Show action menu for a selected package.

    Returns:
        "add:<pkg>", "remove:<pkg>", "print:<pkg>", or None if cancelled.
    """
    actions = ["add", "remove", "print"]

    # Try fzf first
    if _has_fzf():
        cmd = [
            "fzf",
            "--prompt",
            f"{pkg_name}> ",
            "--header",
            "What would you like to do?",
            "--no-multi",
            "--height",
            "15%",
            "--reverse",
        ]

        if preview_fn:
            cmd.extend(
                [
                    "--preview",
                    f"echo {pkg_name}",
                    "--preview-window",
                    "down:60%:wrap",
                ]
            )

        proc = subprocess.run(
            cmd,
            input="\n".join(actions),
            capture_output=True,
            text=True,
            check=False,
        )

        if proc.returncode != 0:
            return None
        choice = proc.stdout.strip()
        if choice in actions:
            return f"{choice}:{pkg_name}"
        return None

    # Fallback: curses menu
    result = curses.wrapper(_curses_action_menu, pkg_name, actions, preview_fn)
    return result


def _curses_action_menu(stdscr, pkg_name: str, actions: list[str], preview_fn=None) -> str | None:
    """Curses action menu."""
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)

    selected = 0
    preview_text = ""
    height, width = stdscr.getmaxyx()

    while True:
        stdscr.clear()

        # Title
        stdscr.addnstr(0, 0, f" pkg: {pkg_name}", width, curses.color_pair(2) | curses.A_BOLD)
        stdscr.addnstr(1, 0, "", width)
        stdscr.addnstr(2, 0, " What would you like to do?", width, curses.A_BOLD)

        for i, action in enumerate(actions):
            y = 3 + i
            label = f"  {i + 1}: {action}"
            if i == selected:
                stdscr.addnstr(y, 0, f" >{label}", width, curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.addnstr(y, 0, label, width)

        # Preview
        if preview_fn and preview_text:
            preview_x = width // 2 + 2
            preview_width = width // 2 - 2
            if preview_width > 10:
                for j, line in enumerate(preview_text.splitlines()[: height - 4]):
                    if j + 4 < height:
                        stdscr.addnstr(j + 4, preview_x, line[:preview_width], preview_width)

        # Help
        help_text = " Enter: select  Esc: cancel  1/2/3: quick select"
        if height > 5:
            stdscr.addnstr(height - 1, 0, help_text, width)

        stdscr.refresh()

        key = stdscr.getch()

        if key == 27:  # Esc
            return None
        elif key == curses.KEY_UP:
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN:
            selected = min(len(actions) - 1, selected + 1)
        elif key == 10:  # Enter
            return f"{actions[selected]}:{pkg_name}"
        elif key == ord("1"):
            return f"add:{pkg_name}"
        elif key == ord("2"):
            return f"remove:{pkg_name}"
        elif key == ord("3"):
            return f"print:{pkg_name}"
