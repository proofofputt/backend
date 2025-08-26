### Git History Cleanup Instructions (Removing 'data/' directory)

**WARNING: This is a sensitive operation that rewrites your repository's history. It should be done with extreme caution, especially if others have already cloned your repository, as it will require them to re-clone or force-update their local copies.**

**The recommended tool for this is `git filter-repo`.**

**Here's how you would typically do it:**

1.  **Install `git filter-repo`:**
    `pip install git-filter-repo` (or follow their installation instructions: [https://github.com/newren/git-filter-repo#installation](https://github.com/newren/git-filter-repo#installation))

2.  **Make a fresh clone:**
    It's highly recommended to work on a fresh clone of your repository to avoid accidentally corrupting your main working copy. Replace `your-username` with your actual GitHub username.
    `git clone git@github.com:your-username/pop.git proofofputt_clean`
    `cd proofofputt_clean`

3.  **Run `git filter-repo` to remove the `data/` directory:**
    This command will rewrite your history to remove all traces of the `data/` directory.
    `git filter-repo --path data/ --invert-paths`

4.  **Force push to GitHub:**
    Because you've rewritten history, you'll need to force push to overwrite the remote repository. **Be absolutely sure this is what you want to do.**
    `git push --force --all`

5.  **Communicate with collaborators:**
    If anyone else has cloned your repository, they will need to delete their local clone and re-clone the repository after you force push.

**Given the complexity and risks, I strongly advise against performing this operation unless absolutely necessary and you fully understand the implications.** For most projects, simply adding `data/` to `.gitignore` is sufficient to prevent future commits of its contents.
