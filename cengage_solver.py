import os
import random
import re
import time
from playwright.sync_api import sync_playwright

ASSIGNMENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assignments.txt")


def open_activity(page, activity_title=None):

    print("Waiting for reader iframe...")

    page.wait_for_selector("iframe[id='1_NB_Main_IFrame']")

    reader = page.frame_locator("iframe[id='1_NB_Main_IFrame']")

    print("Expanding activity...")

    reader.locator("span[id^='expand_button']").first.wait_for()
    
    if activity_title:
        print(f"Looking for activity matching: '{activity_title}'")
        buttons = reader.locator("span[id^='expand_button']")
        count = buttons.count()
        clicked = False
        
        # Try direct substring match first
        for i in range(count):
            btn = buttons.nth(i)
            aria_label = btn.get_attribute("aria-label") or ""
            text = btn.inner_text() or ""
            if activity_title.lower() in aria_label.lower() or activity_title.lower() in text.lower():
                print(f"  Found exact matching activity: {aria_label or text}")
                btn.click()
                clicked = True
                break
                
        # Fallback to loose word matching if no exact substring
        if not clicked:
            title_words = set(activity_title.lower().split())
            best_match = None
            best_score = 0
            best_match_name = ""
            for i in range(count):
                btn = buttons.nth(i)
                lbl = (btn.get_attribute("aria-label") or "") + " " + (btn.inner_text() or "")
                lbl_words = set(lbl.lower().split())
                score = len(title_words.intersection(lbl_words))
                if score > best_score:
                    best_score = score
                    best_match = btn
                    best_match_name = lbl
            
            if best_match and best_score > 0:
                print(f"  Found fuzzy matching activity: {best_match_name} (score {best_score})")
                best_match.click()
                clicked = True
                
        if not clicked:
            print("  Could not find matching activity, falling back to first activity.")
            reader.locator("span[id^='expand_button']").first.click()
    else:
        reader.locator("span[id^='expand_button']").first.click()

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

    print("Solving quiz...")

    frame.locator("input[type='radio']:visible").first.wait_for()

    all_correct = True

    while True:

        # Read current question progress BEFORE solving
        progress = get_question_progress(frame)
        if progress:
            current_q, total_q = progress
            print(f"--- Question {current_q} of {total_q} ---")
        else:
            print("Could not determine question progress. Stopping.")
            break

        radios = frame.locator("input[type='radio']:visible")
        count = radios.count()

        if count == 0:
            print("No visible answers found.")
            break

        found_correct = False
        tried_indices = set()
        max_passes = 3

        for pass_num in range(max_passes):
            indices = random.sample(range(count), count)
            delay = 1.0 + (pass_num * 0.3)

            for i in indices:
                # Click the radio button
                radios.nth(i).click(force=True)
                time.sleep(0.3)

                # Click Check My Work — wait for it to appear first
                try:
                    check_btn = frame.locator(".check-my-work-link:visible").first
                    check_btn.wait_for(timeout=10000)
                    check_btn.click(force=True)
                except Exception:
                    print(f"  Choice {i + 1}: Could not click Check My Work. Skipping.")
                    tried_indices.add(i)
                    continue

                # Wait for feedback to appear (may take a moment on quizzes)
                try:
                    feedback_el = frame.locator(".feedbackWidgetOverallRejoinder:visible").first
                    feedback_el.wait_for(timeout=15000)
                    time.sleep(delay)
                    feedback = feedback_el.inner_text()
                except Exception:
                    print(f"  Choice {i + 1}: Feedback timed out. Skipping.")
                    tried_indices.add(i)
                    continue

                if "Incorrect" not in feedback:
                    print(f"  Correct answer found (choice {i + 1}).")
                    found_correct = True
                    break
                else:
                    print(f"  Choice {i + 1}: Incorrect")
                    tried_indices.add(i)

            if found_correct:
                break
            else:
                print(f"  Pass {pass_num + 1}/{max_passes} exhausted. Retrying with longer delay...")

        if not found_correct:
            all_correct = False
            print("  WARNING: Could not find correct answer for this question.")

        # Check if we're on the last question
        if current_q >= total_q:
            if all_correct:
                print("All questions answered correctly! Submitting assignment...")
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
                                print(f"  Found submit button with selector: {sel}")
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
                                print("  Submit button not found by selector. Pixel scanning above question banner...")
                                for y_offset in range(10, 200, 10):
                                    print(f"    Trying {y_offset}px above banner...")
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
                        print("  Clicking center of screen and pressing Enter to confirm submission...")
                        page_ref = frame.page if hasattr(frame, 'page') else frame
                        viewport = page_ref.viewport_size
                        if viewport:
                            page_ref.mouse.click(viewport['width'] // 2, viewport['height'] // 2)
                        time.sleep(0.5)
                        page_ref.keyboard.press("Enter")
                        time.sleep(1)
                        print("Assignment submitted successfully!")
                    else:
                        print("Could not find submit button. Please submit manually.")
                except Exception as e:
                    print(f"  Auto-submit failed: {e}. Please submit manually.")
            else:
                print("Reached final question but not all answers were correct. Skipping auto-submit.")
            break

        # Navigate to next question using coordinate-based click on the banner
        print(f"Navigating to question {current_q + 1}...")

        nav_info = frame.locator("#takeQuestionNumber:visible")
        if nav_info.count() == 0:
            print("Could not find '#takeQuestionNumber'. Stopping.")
            break
            
        box = nav_info.first.bounding_box()
        if box:
            print("  Clicking right edge of #takeQuestionNumber banner (guess and check)...")
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
                print(f"    Trying click offset: {offset}px from right edge...")
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
                    print(f"    Success! Transitioned to Question {expected_q}.")
                    break
                    
            if not clicked_successfully:
                print(f"  Warning: Exhausted coordinate clicking without detecting transition to Question {expected_q}. Attempting to continue...")
        else:
            print("  Could not determine bounding box for #takeQuestionNumber. Cannot coordinate-click.")
            break

        # Wait for new radio buttons to appear
        frame.locator("input[type='radio']:visible").first.wait_for()
        time.sleep(1)  # Let old feedback clear before trying new question



def main():
    
    # Read assignment URLs from file
    if not os.path.exists(ASSIGNMENTS_FILE):
        print(f"Error: {ASSIGNMENTS_FILE} not found.")
        return

    with open(ASSIGNMENTS_FILE, "r") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not urls:
        print("No assignment URLs found in assignments.txt.")
        return

    print(f"Found {len(urls)} assignment(s) to solve.")

    with sync_playwright() as p:

        print("Launching browser with saved Brightspace login...")

        browser = p.chromium.launch(headless=False, slow_mo=0)

        context = browser.new_context(
            storage_state="brightspace_auth.json"
        )

        for idx, url in enumerate(urls):
            print(f"\n{'='*60}")
            print(f"Assignment {idx + 1} of {len(urls)}: {url}")
            print(f"{'='*60}")

            try:
                page = context.new_page()

                print("Opening Brightspace page...")
                page.goto(url)
                page.wait_for_load_state()

                print("Detecting Brightspace activity title...")
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
                print(f"  Detected title: '{activity_title}'")

                # Detect assignment type: quiz vs listening activity
                is_quiz = bool(re.search(r'chapter\s+\d+\s+quiz', activity_title, re.IGNORECASE))

                print("Opening MindTap assignment...")

                with context.expect_page() as new_page_info:
                    page.locator("text=Open in New Window").click()

                mindtap_page = new_page_info.value
                mindtap_page.wait_for_load_state()

                if is_quiz:
                    print(f"Detected QUIZ: '{activity_title}'")
                    quiz_frame = open_quiz(mindtap_page)
                else:
                    print(f"Detected ACTIVITY: '{activity_title}'")
                    quiz_frame = open_activity(mindtap_page, activity_title)

                solve_quiz(quiz_frame)

                print(f"Finished assignment {idx + 1}: {activity_title}")

                # Close the MindTap tab and Brightspace tab before next assignment
                mindtap_page.close()
                page.close()

            except Exception as e:
                print(f"Error on assignment {idx + 1} ({url}): {e}")
                print("Skipping to next assignment...")
                # Close any open pages from this attempt
                for p_page in context.pages:
                    try:
                        p_page.close()
                    except Exception:
                        pass

        print(f"\n{'='*60}")
        print(f"All {len(urls)} assignment(s) processed!")
        print(f"{'='*60}")

        input("Press Enter to close browser.")


main()
