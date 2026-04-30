use clap::Parser;
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "cfor-mcp", about = "Personal Finance Console MCP server")]
struct Args {
    #[arg(long, default_value = "finance.sqlite3")]
    db: PathBuf,
}

fn main() {
    let args = Args::parse();
    cfor::db::init_db(&args.db).expect("DBの初期化に失敗しました");
    cfor::mcp::server::serve(&args.db);
}
