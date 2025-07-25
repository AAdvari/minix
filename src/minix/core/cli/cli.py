import typer

app = typer.Typer(help="Your Framework CLI")

@app.command()
def init(project: str = "my_project"):
    """Initialize a new project folder"""
    typer.echo(f"Initializing {project}...")
    # Do your actual setup logic here
    # Example: create folder, copy template, etc.

@app.command()
def version():
    """Show the framework version"""
    import minix
    typer.echo(f"Your Framework version: {minix.__version__}")

if __name__ == "__main__":
    app()
