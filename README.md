# Cengage Solver

An automated script that signs into Brightspace, opens Cengage MindTap assignments (quizzes and listening activities), solves them by exhaustively checking possible answers, and auto-submits them when correct.

## 1. Initial Setup (One-time)

**Install Dependencies:**
Make sure you have Python installed, then install Playwright and its browser binaries:
```bash
pip install playwright
playwright install
```

**Save Login Credentials:**
Run the login script once to sign into Brightspace and save your authentication session:
```bash
python save_brightspace_login.py
```
- A browser window will open.
- Log into Brightspace manually.
- Pass Duo/2FA authentication.
- Once you reach the Brightspace dashboard and the page fully loads, the script will automatically save your session token to `brightspace_auth.json` and close the browser.

## 2. Add Assignments

Find the Brightspace links for the assignments you want to complete and add them to the `assignments.txt` file (one URL per line). You can use `#` to comment out lines.

Example `assignments.txt`:
```text
https://purdue.brightspace.com/d2l/le/content/...
https://purdue.brightspace.com/d2l/le/content/...
```

## 3. Run the Auto Solver

Once you have your assignments listed, run the solver:
```bash
python cengage_solver.py
```

- It will load your saved Brightspace session.
- Process each assignment link sequentially.
- If it's a Quiz or Activity, it'll interact with the UI, brute-force answer choices until the correct one is found, navigate to the next question, and repeat.
- Upon successful completion of all questions in an assignment, it auto-submits the assignment for grading.
- It will leave the Brightspace tabs open at the end for your review.
