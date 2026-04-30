use clap::Parser;
use std::path::PathBuf;

use cfor::db::{default_db_path, init_db};

#[derive(Parser)]
#[command(name = "cfor-tui", about = "Personal Finance Console TUI")]
struct Args {
    #[arg(long, default_value_os_t = default_db_path())]
    db: PathBuf,
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    init_db(&args.db)?;
    cfor::tui::app::run_tui(args.db)?;
    Ok(())
}
