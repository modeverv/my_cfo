use clap::Parser;
use std::io::{self, BufRead, Write};
use std::path::PathBuf;

use cfor::commands::handle_command;
use cfor::db::{connect, default_db_path, init_db};

#[derive(Parser)]
#[command(name = "cfor", about = "Personal Finance Console")]
struct Args {
    #[arg(long, default_value_os_t = default_db_path())]
    db: PathBuf,

    #[arg(long, help = "TUIモードで起動")]
    tui: bool,

    #[arg(trailing_var_arg = true)]
    command: Vec<String>,
}

fn repl(db_path: &PathBuf) -> anyhow::Result<()> {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = io::BufWriter::new(stdout.lock());

    loop {
        write!(out, "fin> ")?;
        out.flush()?;

        let mut line = String::new();
        match stdin.lock().read_line(&mut line) {
            Ok(0) => {
                writeln!(out)?;
                break;
            }
            Ok(_) => {}
            Err(e) => return Err(e.into()),
        }

        let line = line.trim();
        if line == "q" || line == "quit" || line == "exit" {
            break;
        }
        if line.is_empty() {
            continue;
        }

        match connect(db_path) {
            Ok(conn) => match handle_command(&conn, line) {
                Ok(output) => {
                    let _ = conn.execute_batch("COMMIT");
                    if !output.is_empty() {
                        writeln!(out, "{}", output)?;
                    }
                }
                Err(e) => {
                    let _ = conn.execute_batch("ROLLBACK");
                    writeln!(out, "ERROR: {}", e)?;
                }
            },
            Err(e) => {
                writeln!(out, "DB ERROR: {}", e)?;
            }
        }
        out.flush()?;
    }
    Ok(())
}

fn run_single_command(db_path: &PathBuf, command_line: &str) -> anyhow::Result<()> {
    let conn = connect(db_path)?;
    match handle_command(&conn, command_line) {
        Ok(output) => {
            let _ = conn.execute_batch("COMMIT");
            if !output.is_empty() {
                println!("{}", output);
            }
            Ok(())
        }
        Err(e) => {
            let _ = conn.execute_batch("ROLLBACK");
            Err(anyhow::anyhow!("{}", e))
        }
    }
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    init_db(&args.db)?;

    if args.tui {
        cfor::tui::app::run_tui(args.db)?;
        return Ok(());
    }

    if args.command.is_empty() {
        repl(&args.db)?;
        return Ok(());
    }

    let command_line = args.command.join(" ");
    if let Err(e) = run_single_command(&args.db, &command_line) {
        eprintln!("ERROR: {}", e);
        std::process::exit(1);
    }
    Ok(())
}
