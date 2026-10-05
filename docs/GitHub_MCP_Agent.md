# GitHub MCP Agent

The GitHub MCP Agent is a specialized agent that uses GitHub MCP (Model Context Protocol) tools for repository management and development workflows. It's built using LangGraph's `create_react_agent` for a clean, ReAct (Reasoning and Acting) pattern implementation.

**This agent is designed as a demo for agents that use MCP (Model Context Protocol) servers and tools.**

## Features

[The Github MCP server](https://github.com/github/github-mcp-server) provides a variety of tools, if a PAT is configured.

- Repository management (create, clone, browse)
- Issue management (create, list, update, close)
- Pull request management (create, review, merge)
- Branch management (create, switch, merge)
- File operations (read, write, search)
- Commit operations (create, view history)

## Connect GitHub (recommended)

In the web UI, each person clicks **Connect GitHub** in the sidebar, approves access on github.com,
and the agent then works with *their* repositories. No one has to create a token by hand.

1. Create a GitHub App: **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
   - Homepage URL: `http://localhost:3000`
   - Callback URL: `http://localhost:3000/api/github/callback` (add your hosted URL too when you deploy)
   - Tick **Request user authorization (OAuth) during installation**; leave **Allow wildcard matching** off
   - Webhook: untick **Active**
   - Repository permissions: Contents *Read-only*, Issues *Read and write*, Pull requests *Read and write*
     (Metadata is added automatically). Leave organization, account and enterprise permissions at *No access*.
2. Copy the **Client ID**, generate a **Client secret**, and add them to `.env` with a cookie key:

   ```bash
   GITHUB_CLIENT_ID=Iv23li...
   GITHUB_CLIENT_SECRET=...
   WEB_SESSION_SECRET=$(openssl rand -base64 32)   # paste the generated value
   ```

   Also add `GITHUB_APP_SLUG`, the last part of the app's **Public link** (`https://github.com/apps/<slug>`).
   With it, users who haven't installed the app yet go straight to GitHub's "choose repositories" page
   after authorizing. The App ID and private key aren't needed.
3. Restart `./run.sh`, open <http://localhost:3000> and click **Connect GitHub**.

How the token is handled: the web server keeps each user's token in an encrypted, httpOnly cookie and
sends it to the service only for GitHub agent requests (`X-GitHub-Token` header). The service passes it
to the GitHub tools as LangGraph run context, so it is never written to checkpoints, thread metadata or
traces. Tokens refresh automatically, and **Disconnect** revokes the authorization on GitHub. The sidebar's
GitHub menu also has **Choose repositories** to change which repos the app can reach.

Private repositories are only visible once the app is *installed* on them. Authorizing alone gives access
to your identity and public data, so a private repo returns 404 until it's selected in the install step.

## Configuration

The settings below are for using the agent without the web UI (API or Streamlit), with one shared token.

To enable the GitHub MCP Agent, you need to configure the following environment variables:

### Required Settings

```bash
# GitHub Personal Access Token (fallback when a request carries no user token)
GITHUB_PAT=your_github_personal_access_token_here
```

### Optional Settings

```bash
# GitHub MCP server URL (defaults to https://api.githubcopilot.com/mcp/)
MCP_GITHUB_SERVER_URL=https://api.githubcopilot.com/mcp/
```

## GitHub Personal Access Token

To use the GitHub MCP Agent, you need a GitHub Personal Access Token (PAT) with appropriate permissions. The GitHub MCP server provides a wide variety of tools for repository management, and different tools require different scopes.

1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate a new token with the following scopes:
   - `repo` (Full control of private repositories) - Enables tools like `create_issue`, `create_pull_request`, `get_file_contents`, `list_commits`
   - `read:org` (Read org and team membership) - Enables organization-related tools
   - `read:user` (Read user profile data) - Enables user profile tools
   - `user:email` (Access user email addresses) - Enables email-related functionality

**Note**: The specific tools available depend on your PAT scopes. With the recommended scopes above, you'll have access to most repository management tools including creating issues, pull requests, reading file contents, and listing commits.

## Usage

Once configured, the GitHub MCP Agent will be available as `github-mcp-agent` in the service.

### Example Prompts

Here are some example prompts you can use with the GitHub MCP Agent:

- **"Describe the qwertyz15/agent-service-toolkit repository"** - Shows repository information and README content
- **"List the recent commits in this repository"** - Displays recent commit history
- **"What files are in the src directory?"** - Lists files in a specific directory
- **"Show me the README file"** - Displays repository README content
- **"Create a new issue titled 'Bug: Login not working' with the description 'The login form is not responding to user input'"** - Creates a new issue
- **"What are the open issues in this repository?"** - Lists open issues
- **"Create a pull request from feature-branch to main with the title 'Add new feature'"** - Creates a pull request
- **"Show me information about this repository"** - Displays repository details
