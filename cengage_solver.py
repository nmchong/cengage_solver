import os
import random
import re
import time
from playwright.sync_api import sync_playwright
from llm_client import get_ranking
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

ASSIGNMENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assignments.txt")
console = Console()

def open_activity(page, activity_title=None):

    print("Waiting for reader iframe...")

    page.wait_for_selector("iframe[id='1_NB_Main_IFrame']")

    reader = page.frame_locator("iframe[id='1_NB_Main_IFrame']")

    print("Expanding activity...")

    reader.locator("span[id^='expand_button']").first.wait_for()
    time.sleep(2)  # Let all expand buttons render and stabilize
    
    if activity_title:
        print(f"Looking for activity matching: '{activity_title}'")
        buttons = reader.locator("span[id^='expand_button']")
        count = buttons.count()
        clicked = False
        
        # Extract number pattern (e.g. '6-1', '7-2') from the title for precise matching
        title_number = re.search(r'(\d+-\d+)', activity_title)
        
        # Try exact substring match first
        for i in range(count):
            btn = buttons.nth(i)
            aria_label = btn.get_attribute("aria-label") or ""
            text = btn.inner_text() or ""
            label = aria_label + " " + text
            if activity_title.lower() in label.lower():
                print(f"  Found exact matching activity: {aria_label or text}")
                btn.click(force=True)
                clicked = True
                break
        
        # Try matching by number pattern (e.g. '7-1')
        if not clicked and title_number:
            target_num = title_number.group(1)
            for i in range(count):
                btn = buttons.nth(i)
                label = (btn.get_attribute("aria-label") or "") + " " + (btn.inner_text() or "")
                if target_num in label:
                    print(f"  Found number-matched activity ({target_num}): {label.strip()}")
                    btn.click(force=True)
                    clicked = True
                    break
                
        if not clicked:
            print(f"  Could not find matching activity among {count} buttons, falling back to first activity.")
            reader.locator("span[id^='expand_button']").first.click(force=True)
    else:
        reader.locator("span[id^='expand_button']").first.click(force=True)

    print("Searching all frames for Start/Resume button...")

    # Search all frames for #startButton (the expanded activity's frame will have it)
    quiz_frame = None
    max_retries = 10
    for attempt in range(max_retries):
        for f in page.frames:
            try:
                btn = f.locator("#startButton")
                if btn.count() > 0:
                    frame_name = f.url[:80] if f.url else f.name or "unnamed"
                    print(f"  Found Start button in frame: {frame_name}")
                    btn.first.click()
                    quiz_frame = f
                    break
            except Exception:
                continue
        if quiz_frame:
            break
        time.sleep(1)

    if quiz_frame is None:
        raise Exception("Could not find #startButton in any frame.")

    print("Waiting for quiz answers to load...")
    quiz_frame.locator("input[type='radio']:visible").first.wait_for(timeout=15000)

    return quiz_frame


def open_quiz(page):
    """Open a quiz on the MindTap page. Searches all frames for the Start button."""

    print("Waiting for MindTap quiz page to fully load...")
    page.wait_for_load_state("networkidle")
    time.sleep(1)  # Brief buffer for quiz redirects to settle

    print("Searching all frames for Start/Resume button...")

    # Try the main page first
    all_targets = [("main page", page)]

    # Collect all frames
    for f in page.frames:
        all_targets.append((f.url or f.name or "unnamed frame", f))

    quiz_frame = None
    for name, target in all_targets:
        try:
            btn = target.locator("#startButton")
            if btn.count() > 0:
                print(f"  Found Start button in: {name}")
                btn.first.click()
                quiz_frame = target
                break
        except Exception:
            continue

    if quiz_frame is None:
        # Maybe frames haven't loaded yet, wait and retry
        print("  Start button not found yet. Waiting 2 more seconds and retrying...")
        time.sleep(2)
        for f in page.frames:
            try:
                btn = f.locator("#startButton")
                if btn.count() > 0:
                    print(f"  Found Start button in frame: {f.url or f.name}")
                    btn.first.click()
                    quiz_frame = f
                    break
            except Exception:
                continue

    if quiz_frame is None:
        raise Exception("Could not find #startButton in any frame on the quiz page.")

    print("  Waiting for quiz answers to load...")
    quiz_frame.locator("input[type='radio']:visible").first.wait_for(timeout=15000)
    return quiz_frame


def get_question_progress(frame):
    """Parse 'Question X of Y' from #takeQuestionNumber. Returns (current, total) or None."""
    nav_info = frame.locator("#takeQuestionNumber:visible")
    if nav_info.count() == 0:
        return None
    nav_text = nav_info.first.inner_text()
    match = re.search(r"Question\s+(\d+)\s+of\s+(\d+)", nav_text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def solve_quiz(frame):

    console.print(Panel("[bold cyan]Starting Quiz Solver[/bold cyan]", border_style="cyan"))

    frame.locator("input[type='radio']:visible").first.wait_for()

    all_correct = True

    while True:

        # Read current question progress BEFORE solving
        progress = get_question_progress(frame)
        if progress:
            current_q, total_q = progress
            console.print(f"\n[bold reverse] --- Question {current_q} of {total_q} --- [/bold reverse]")
        else:
            console.print("[bold red]Could not determine question progress. Stopping.[/bold red]")
            break

        radios = frame.locator("input[type='radio']:visible")
        count = radios.count()

        if count == 0:
            console.print("[yellow]No visible answers found.[/yellow]")
            break

        # Extract question text
        question_text = ""
        try:
            q_selectors = [
                "#takeQuestionText", 
                ".question-text", 
                ".questionText", 
                ".q-text",
                ".problemTypes",
                "div[id$='_question']"
            ]
            for sel in q_selectors:
                loc = frame.locator(sel)
                if loc.count() > 0:
                    question_text = loc.first.inner_text().strip()
                    if question_text:
                        console.print(f"  [dim]Extracted question using '{sel}':[/dim] [italic]{question_text[:100]}...[/italic]")
                        break
            if not question_text:
                console.print("  [dim red]Failed to extract question text with any selector.[/dim red]")
        except Exception as e:
            console.print(f"  [red]Error extracting question text: {e}[/red]")

        # Extract answer labels
        labels = []
        for i in range(count):
            label_text = f"Choice {i+1}"
            try:
                radio = radios.nth(i)
                radio_id = radio.get_attribute("id")
                if radio_id:
                    label_loc = frame.locator(f"label[for='{radio_id}']")
                    if label_loc.count() > 0:
                        label_text = label_loc.first.inner_text().strip()
                
                if not label_text or label_text == f"Choice {i+1}":
                    label_text = radio.evaluate("el => el.parentElement.innerText").strip()
            except Exception:
                pass
            labels.append(label_text)
        
        # Display choices in a table
        table = Table(title="Answer Choices", show_header=False, box=None)
        for i, label in enumerate(labels):
            table.add_row(f"[bold]{i+1}.[/bold]", label)
        console.print(table)

        # Extract page context (e.g. from container-page)
        page_context = ""
        try:
            # Context selectors: prioritize the active section and content area
            context_selectors = [".content", ".container.page", ".container-page", ".activity-container", "#activity-container", "main"]
            for sel in context_selectors:
                loc = frame.locator(sel)
                if loc.count() > 0:
                    page_context = loc.first.inner_text().strip()
                    if page_context:
                        console.print(f"  [dim]Extracted context ({len(page_context)} chars) from current frame using '{sel}'[/dim]")
                        break
            
            # If not found, check the parent frames
            if not page_context:
                page_ref = frame.page if hasattr(frame, 'page') else frame
                for f in page_ref.frames:
                    if f == frame: continue
                    for sel in context_selectors:
                        try:
                            loc = f.locator(sel)
                            if loc.count() > 0:
                                text = loc.first.inner_text().strip()
                                if text and len(text) > 100:
                                    page_context = text
                                    console.print(f"  [dim]Extracted context ({len(page_context)} chars) from frame '{f.name or 'unnamed'}' using '{sel}'[/dim]")
                                    break
                        except Exception:
                            continue
                    if page_context:
                        break
        except Exception as e:
            console.print(f"  [dim red]Error extracting page context: {e}[/dim red]")

        if page_context:
            page_context = page_context[:4000]
        else:
            console.print("  [dim yellow]No page context found in any frame.[/dim yellow]")

        # Get ranking from LLM
        llm_indices = []
        has_real_labels = any(l for l in labels if l and not l.startswith("Choice "))
        if question_text and has_real_labels:
            console.print("  [bold blue]Asking LLM to rank choices...[/bold blue]")
            try:
                llm_indices = get_ranking(question_text, labels, page_context=page_context)
            except Exception as e:
                console.print(f"  [bold red]LLM ranking failed: {e}[/bold red]")
                llm_indices = []
        else:
            reason = "Missing question text" if not question_text else "No descriptive labels"
            console.print(f"  [dim yellow]Skipping LLM ranking: {reason}[/dim yellow]")

        found_correct = False
        tried_indices = set()
        max_passes = 3

        for pass_num in range(max_passes):
            is_valid_ranking = (
                llm_indices and 
                len(llm_indices) == count and 
                sorted(llm_indices) == list(range(count))
            )
            
            if pass_num == 0 and is_valid_ranking:
                indices = llm_indices
                mode_desc = "[bold green]LLM-Ranked Order[/bold green]"
            else:
                indices = random.sample(range(count), count)
                mode_desc = f"[bold yellow]Random Pass {pass_num+1}[/bold yellow]"
            
            console.print(f"  [bold cyan]Attempting: {mode_desc}[/bold cyan]")
            delay = 1.0 + (pass_num * 0.3)

            for i in indices:
                # Click the radio button
                console.print(f"    - Testing choice [bold]{i+1}[/bold]...", end="")
                radios.nth(i).click(force=True)
                time.sleep(0.3)

                # Click Check My Work
                try:
                    check_btn = frame.locator(".check-my-work-link:visible").first
                    check_btn.wait_for(timeout=10000)
                    check_btn.click(force=True)
                except Exception:
                    console.print(" [red]Failed to click 'Check My Work'[/red]")
                    tried_indices.add(i)
                    continue

                # Wait for feedback
                try:
                    feedback_el = frame.locator(".feedbackWidgetOverallRejoinder:visible").first
                    feedback_el.wait_for(timeout=15000)
                    time.sleep(delay)
                    feedback = feedback_el.inner_text()
                except Exception:
                    console.print(" [red]Feedback timeout[/red]")
                    tried_indices.add(i)
                    continue

                if "Incorrect" not in feedback:
                    console.print(" [bold green]CORRECT![/bold green]")
                    found_correct = True
                    break
                else:
                    console.print(" [dim red]Incorrect[/dim red]")
                    tried_indices.add(i)

            if found_correct:
                break
            else:
                console.print(f"  [bold yellow]Pass {pass_num + 1} exhausted. Retrying...[/bold yellow]")

        if not found_correct:
            all_correct = False
            console.print("  [bold red]WARNING: Could not find correct answer for this question.[/bold red]")

        # Check if we're on the last question
        if current_q >= total_q:
            if all_correct:
                console.print("[bold green]All questions answered correctly! Submitting...[/bold green]")
                try:
                    submitted = False

                    # Try multiple selectors for the Submit button
                    selectors = [
                        "button:has-text('Submit Assignment for Grading')",
                        "text=Submit Assignment for Grading",
                        "button:has-text('Submit')",
                        ".submit-for-grading-button",
                        "input[value*='Submit']",
                    ]
                    for sel in selectors:
                        try:
                            btn = frame.locator(sel)
                            if btn.count() > 0:
                                console.print(f"  [dim]Found submit button with selector: {sel}[/dim]")
                                btn.first.click(force=True)
                                submitted = True
                                break
                        except Exception:
                            continue

                    if not submitted:
                        # Pixel scan above #takeQuestionNumber to find the submit button
                        nav_info = frame.locator("#takeQuestionNumber:visible")
                        if nav_info.count() > 0:
                            box = nav_info.first.bounding_box()
                            if box:
                                console.print("  [dim]Submit button not found by selector. Pixel scanning above question banner...[/dim]")
                                for y_offset in range(10, 200, 10):
                                    nav_info.first.click(
                                        position={"x": box["width"] / 2, "y": -y_offset},
                                        force=True
                                    )
                                    time.sleep(1)
                                    submitted = True
                                    break

                    if submitted:
                        time.sleep(2)
                        # Click center of viewport to focus the popup dialog, then press Enter
                        page_ref = frame.page if hasattr(frame, 'page') else frame
                        viewport = page_ref.viewport_size
                        if viewport:
                            page_ref.mouse.click(viewport['width'] // 2, viewport['height'] // 2)
                        time.sleep(0.5)
                        page_ref.keyboard.press("Enter")
                        time.sleep(1)
                        console.print("[bold green]Assignment submitted successfully![/bold green]")
                    else:
                        console.print("[bold yellow]Could not find submit button. Please submit manually.[/bold yellow]")
                except Exception as e:
                    console.print(f"  [red]Auto-submit failed: {e}. Please submit manually.[/red]")
            else:
                console.print("[bold yellow]Reached final question but not all answers were correct. Skipping auto-submit.[/bold yellow]")
            break

        # Navigate to next question using coordinate-based click on the banner
        console.print(f"[cyan]Navigating to question {current_q + 1}...[/cyan]")

        nav_info = frame.locator("#takeQuestionNumber:visible")
        if nav_info.count() == 0:
            console.print("[bold red]Could not find '#takeQuestionNumber'. Stopping.[/bold red]")
            break
            
        box = nav_info.first.bounding_box()
        if box:
            clicked_successfully = False
            expected_q = current_q + 1
            max_wait_per_click = 0.75  # seconds
            
            # Generate spiraling offsets starting at 8px: 8, 10, 12, 6, 14, 4, 16, 2...
            offsets = [8]
            for i in range(1, 45):
                offsets.append(8 + i * 2)
                if 8 - i * 2 > 0:
                    offsets.append(8 - i * 2)

            for offset in offsets:
                nav_info.first.click(position={"x": box["width"] - offset, "y": box["height"] / 2}, force=True)
                
                # Check for transition
                waited = 0
                while waited < max_wait_per_click:
                    time.sleep(0.1)
                    waited += 0.1
                    new_progress = get_question_progress(frame)
                    if new_progress and new_progress[0] == expected_q:
                        clicked_successfully = True
                        break
                        
                if clicked_successfully:
                    break
                    
            if not clicked_successfully:
                console.print(f"  [bold yellow]Warning: Detecting transition to Question {expected_q} failed.[/bold yellow]")
        else:
            console.print("[bold red]Could not determine bounding box for #takeQuestionNumber.[/bold red]")
            break

        # Wait for new radio buttons to appear
        frame.locator("input[type='radio']:visible").first.wait_for()
        time.sleep(1)  # Let old feedback clear before trying new question



def main():
    
    # Read assignment URLs from file
    if not os.path.exists(ASSIGNMENTS_FILE):
        console.print(f"[bold red]Error: {ASSIGNMENTS_FILE} not found.[/bold red]")
        return

    with open(ASSIGNMENTS_FILE, "r") as f:
        urls = []
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            # Extract URL: look for http/https in the line
            match = re.search(r'(https?://\S+)', line)
            if match:
                urls.append(match.group(1))
            else:
                # Fallback to the whole line if no protocol found but it's not a comment
                urls.append(line)

    if not urls:
        console.print("[bold yellow]No assignment URLs found in assignments.txt.[/bold yellow]")
        return

    console.print(f"[bold green]Found {len(urls)} assignment(s) to solve.[/bold green]")

    with sync_playwright() as p:

        console.print("Launching browser with saved Brightspace login...")

        browser = p.chromium.launch(headless=False, slow_mo=0)

        context = browser.new_context(
            storage_state="brightspace_auth.json"
        )

        for idx, url in enumerate(urls):
            console.print(f"\n[bold magenta]{'='*60}[/bold magenta]")
            console.print(f"[bold magenta]Assignment {idx + 1} of {len(urls)}: {url}[/bold magenta]")
            console.print(f"[bold magenta]{'='*60}[/bold magenta]")

            try:
                page = context.new_page()

                console.print("Opening Brightspace page...")
                page.goto(url)
                page.wait_for_load_state()

                console.print("Detecting Brightspace activity title...")
                title_loc = page.locator(".d2l-page-title")
                activity_title = None
                if title_loc.count() > 0:
                    activity_title = title_loc.first.inner_text().strip()
                
                if not activity_title:
                    title_loc = page.locator("h1, h2")
                    if title_loc.count() > 0:
                        activity_title = title_loc.first.inner_text().strip()
                
                if not activity_title:
                    activity_title = page.title().split("-")[0].strip()
                console.print(f"  Detected title: '[bold cyan]{activity_title}[/bold cyan]'")

                # Detect assignment type: quiz vs listening activity
                is_quiz = bool(re.search(r'chapter\s+\d+\s+quiz', activity_title, re.IGNORECASE))

                console.print("Opening MindTap assignment...")

                with context.expect_page() as new_page_info:
                    page.locator("text=Open in New Window").click()

                mindtap_page = new_page_info.value
                mindtap_page.wait_for_load_state()

                if is_quiz:
                    console.print(f"Detected [bold yellow]QUIZ[/bold yellow]: '{activity_title}'")
                    quiz_frame = open_quiz(mindtap_page)
                else:
                    console.print(f"Detected [bold yellow]ACTIVITY[/bold yellow]: '{activity_title}'")
                    quiz_frame = open_activity(mindtap_page, activity_title)

                solve_quiz(quiz_frame)

                console.print(f"[bold green]Finished assignment {idx + 1}: {activity_title}[/bold green]")

                # Close ALL pages to avoid frame pollution on next assignment
                for p_page in context.pages:
                    try:
                        p_page.close()
                    except Exception:
                        pass

            except Exception as e:
                console.print(f"[bold red]Error on assignment {idx + 1} ({url}): {e}[/bold red]")
                console.print("Skipping to next assignment...")
                for p_page in context.pages:
                    try:
                        p_page.close()
                    except Exception:
                        pass

        console.print(f"\n[bold magenta]{'='*60}[/bold magenta]")
        console.print(f"[bold magenta]All {len(urls)} assignment(s) processed![/bold magenta]")
        console.print(f"[bold magenta]{'='*60}[/bold magenta]")

        input("Press Enter to close browser.")


main()
