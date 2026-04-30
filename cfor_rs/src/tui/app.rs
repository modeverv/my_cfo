use std::io::{self, Stdout};
use std::path::PathBuf;
use std::sync::mpsc;
use std::thread;

use crossterm::{
    event::{self, Event, KeyCode, KeyModifiers},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Style},
    text::Span,
    widgets::{Block, Borders, List, ListItem, Paragraph},
    Frame, Terminal,
};

use crate::commands::handle_command;
use crate::db::connect;
use crate::models::format_amount;
use crate::services::ask_context::{
    active_card_month, get_card_month_summary, get_recent_transfers, get_wallet_month_summary,
};
use crate::services::snapshots::get_latest_snapshot;

const GREEN: Color = Color::Rgb(0, 255, 102);      // #00ff66 bright highlight
const DIM_GREEN: Color = Color::Rgb(0, 176, 48);   // #00b030 side pane
const MAIN_COLOR: Color = Color::Rgb(0, 224, 64);  // #00e040 main text
const BG_DARK: Color = Color::Rgb(5, 15, 5);       // #050f05 dark background

enum AppMsg {
    LlmResponse(String),
    LlmError(String),
}

struct SidePaneData {
    card_lines: Vec<String>,
    cash_lines: Vec<String>,
    transfer_lines: Vec<String>,
}

pub struct App {
    db_path: PathBuf,
    output_lines: Vec<String>,
    input: String,
    status_line1: String,
    status_line2: String,
    side: SidePaneData,
    llm_rx: Option<mpsc::Receiver<AppMsg>>,
    scroll_offset: u16,
}

impl App {
    pub fn new(db_path: PathBuf) -> Self {
        App {
            db_path,
            output_lines: Vec::new(),
            input: String::new(),
            status_line1: String::new(),
            status_line2: String::new(),
            side: SidePaneData {
                card_lines: Vec::new(),
                cash_lines: Vec::new(),
                transfer_lines: Vec::new(),
            },
            llm_rx: None,
            scroll_offset: 0,
        }
    }

    fn refresh_all(&mut self) {
        if let Ok(conn) = connect(&self.db_path) {
            if let Ok(snap) = get_latest_snapshot(&conn) {
                self.status_line1 = format!(
                    "{}  総資産: {}円",
                    snap.as_of_date,
                    format_amount(snap.total_assets)
                );
                self.status_line2 = format!(
                    "カード: {}円  財布: {}円",
                    format_amount(snap.credit_card_unbilled),
                    format_amount(snap.wallet_total)
                );
            }

            if let Ok(billing) = active_card_month(&conn) {
                if let Ok(summary) = get_card_month_summary(&conn, &billing) {
                    let mut lines = vec![format!(
                        "カード 支払月:{} — {}円",
                        billing,
                        format_amount(summary.total)
                    )];
                    for m in summary.by_merchant.iter().take(5) {
                        lines.push(format!("  {} {}円", m.merchant, format_amount(m.total)));
                    }
                    self.side.card_lines = lines;
                }
            }

            let this_month = chrono::Local::now().format("%Y-%m").to_string();
            if let Ok(wallet_summary) = get_wallet_month_summary(&conn, &this_month) {
                let mut lines = vec![format!(
                    "現金支出 {}月 — {}円",
                    &this_month[5..],
                    format_amount(wallet_summary.cash_out_total)
                )];
                for e in wallet_summary.large_cash_out.iter().take(5) {
                    lines.push(format!("  {} {}円", e.description, format_amount(e.amount)));
                }
                self.side.cash_lines = lines;
            }

            if let Ok(transfers) = get_recent_transfers(&conn, 5) {
                let mut lines = vec!["最近の振替:".to_string()];
                for t in &transfers {
                    lines.push(format!(
                        "  {} {}→{} {}円",
                        t.occurred_on,
                        t.from_account,
                        t.to_account,
                        format_amount(t.amount)
                    ));
                }
                self.side.transfer_lines = lines;
            }
        }
    }

    fn run_command(&mut self, cmd: &str) {
        self.output_lines.push(format!("fin> {}", cmd));

        let is_ask = cmd.trim_start().starts_with("/ask");
        let cmd = cmd.to_string();
        let db_path = self.db_path.clone();

        if is_ask {
            let (tx, rx) = mpsc::channel();
            self.llm_rx = Some(rx);
            self.output_lines.push("LLMに問い合わせ中...".to_string());
            thread::spawn(move || {
                if let Ok(conn) = connect(&db_path) {
                    match handle_command(&conn, &cmd) {
                        Ok(out) => {
                            let _ = tx.send(AppMsg::LlmResponse(out));
                        }
                        Err(e) => {
                            let _ = tx.send(AppMsg::LlmError(e.to_string()));
                        }
                    }
                }
            });
        } else {
            match connect(&self.db_path) {
                Ok(conn) => match handle_command(&conn, &cmd) {
                    Ok(out) => {
                        if !out.is_empty() {
                            for line in out.lines() {
                                self.output_lines.push(line.to_string());
                            }
                        }
                        let _ = conn.execute_batch("COMMIT");
                    }
                    Err(e) => {
                        let _ = conn.execute_batch("ROLLBACK");
                        self.output_lines.push(format!("ERROR: {}", e));
                    }
                },
                Err(e) => {
                    self.output_lines.push(format!("DB ERROR: {}", e));
                }
            }
            self.refresh_all();
        }
        self.scroll_offset = 0;
    }

    fn check_llm(&mut self) {
        let msg = if let Some(rx) = &self.llm_rx {
            rx.try_recv().ok()
        } else {
            None
        };
        if let Some(msg) = msg {
            self.llm_rx = None;
            match msg {
                AppMsg::LlmResponse(out) => {
                    // Remove the "LLMに問い合わせ中..." line
                    if self
                        .output_lines
                        .last()
                        .map(|l| l.contains("LLMに問い合わせ中"))
                        .unwrap_or(false)
                    {
                        self.output_lines.pop();
                    }
                    for line in out.lines() {
                        self.output_lines.push(line.to_string());
                    }
                }
                AppMsg::LlmError(e) => {
                    if self
                        .output_lines
                        .last()
                        .map(|l| l.contains("LLMに問い合わせ中"))
                        .unwrap_or(false)
                    {
                        self.output_lines.pop();
                    }
                    self.output_lines.push(format!("LLM ERROR: {}", e));
                }
            }
        }
    }

    fn draw(&self, f: &mut Frame) {
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(2), // status header
                Constraint::Min(0),    // main area
                Constraint::Length(3), // input bar
            ])
            .split(f.area());

        // Status header
        let status_text = format!("{}\n{}", self.status_line1, self.status_line2);
        let status = Paragraph::new(status_text)
            .style(Style::default().fg(GREEN).bg(BG_DARK))
            .block(
                Block::default()
                    .borders(Borders::BOTTOM)
                    .border_style(Style::default().fg(DIM_GREEN)),
            );
        f.render_widget(status, chunks[0]);

        // Main area split: left 60%, right 40%
        let main_chunks = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(60), Constraint::Percentage(40)])
            .split(chunks[1]);

        self.draw_output(f, main_chunks[0]);
        self.draw_side(f, main_chunks[1]);

        // Input bar
        let input_text = format!("fin> {}", self.input);
        let input = Paragraph::new(input_text)
            .style(Style::default().fg(GREEN).bg(BG_DARK))
            .block(
                Block::default()
                    .borders(Borders::TOP)
                    .border_style(Style::default().fg(DIM_GREEN))
                    .title(Span::styled(
                        " F1:ヘルプ  F2:/now  F3:/card  F4:/cash  F5:/atm 10000  F10:終了 ",
                        Style::default().fg(DIM_GREEN),
                    )),
            );
        f.render_widget(input, chunks[2]);
    }

    fn draw_output(&self, f: &mut Frame, area: Rect) {
        let visible_height = area.height.saturating_sub(2) as usize;
        let total = self.output_lines.len();
        let start = if total > visible_height {
            (total - visible_height).saturating_sub(self.scroll_offset as usize)
        } else {
            0
        };
        let visible: Vec<ListItem> = self.output_lines[start..]
            .iter()
            .map(|l| ListItem::new(l.as_str()).style(Style::default().fg(MAIN_COLOR).bg(BG_DARK)))
            .collect();

        let list = List::new(visible)
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(DIM_GREEN))
                    .title(Span::styled(
                        "  Personal Finance Console  ",
                        Style::default().fg(GREEN),
                    )),
            )
            .style(Style::default().fg(MAIN_COLOR).bg(BG_DARK));
        f.render_widget(list, area);
    }

    fn draw_side(&self, f: &mut Frame, area: Rect) {
        let side_chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Percentage(40),
                Constraint::Percentage(30),
                Constraint::Percentage(30),
            ])
            .split(area);

        fn make_list<'a>(lines: &'a [String], title: &'a str) -> List<'a> {
            let items: Vec<ListItem> = lines
                .iter()
                .map(|l| ListItem::new(l.as_str()).style(Style::default().fg(DIM_GREEN).bg(BG_DARK)))
                .collect();
            List::new(items)
                .block(
                    Block::default()
                        .borders(Borders::ALL)
                        .border_style(Style::default().fg(DIM_GREEN))
                        .title(Span::styled(title, Style::default().fg(GREEN))),
                )
                .style(Style::default().fg(DIM_GREEN).bg(BG_DARK))
        }

        f.render_widget(make_list(&self.side.card_lines, " カード "), side_chunks[0]);
        f.render_widget(
            make_list(&self.side.cash_lines, " 現金支出 "),
            side_chunks[1],
        );
        f.render_widget(
            make_list(&self.side.transfer_lines, " 振替 "),
            side_chunks[2],
        );
    }
}

pub fn run_tui(db_path: PathBuf) -> anyhow::Result<()> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut app = App::new(db_path);
    app.refresh_all();
    app.output_lines
        .push("Personal Finance Console へようこそ".to_string());
    app.output_lines
        .push("/help でコマンド一覧を表示".to_string());

    let result = run_loop(&mut terminal, &mut app);

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;

    result
}

fn run_loop(
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
    app: &mut App,
) -> anyhow::Result<()> {
    loop {
        app.check_llm();
        terminal.draw(|f| app.draw(f))?;

        if event::poll(std::time::Duration::from_millis(100))? {
            if let Event::Key(key) = event::read()? {
                match (key.code, key.modifiers) {
                    (KeyCode::F(10), _) | (KeyCode::Char('q'), KeyModifiers::CONTROL) => {
                        break;
                    }
                    (KeyCode::F(1), _) => {
                        let cmd = "/help".to_string();
                        app.run_command(&cmd);
                    }
                    (KeyCode::F(2), _) => {
                        app.run_command("/now");
                    }
                    (KeyCode::F(3), _) => {
                        app.run_command("/card");
                    }
                    (KeyCode::F(4), _) => {
                        app.run_command("/cash");
                    }
                    (KeyCode::F(5), _) => {
                        app.run_command("/atm 10000");
                    }
                    (KeyCode::Enter, _) => {
                        let cmd = app.input.trim().to_string();
                        app.input.clear();
                        if !cmd.is_empty() {
                            if cmd == "q" || cmd == "quit" || cmd == "exit" {
                                break;
                            }
                            app.run_command(&cmd);
                        }
                    }
                    (KeyCode::Backspace, _) => {
                        app.input.pop();
                    }
                    (KeyCode::Char(c), _) => {
                        app.input.push(c);
                    }
                    (KeyCode::PageUp, _) => {
                        app.scroll_offset = app.scroll_offset.saturating_add(5);
                    }
                    (KeyCode::PageDown, _) => {
                        app.scroll_offset = app.scroll_offset.saturating_sub(5);
                    }
                    _ => {}
                }
            }
        }
    }
    Ok(())
}
