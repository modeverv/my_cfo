use unicode_width::UnicodeWidthChar;

pub fn display_width(s: &str) -> usize {
    s.chars()
        .map(|c| UnicodeWidthChar::width(c).unwrap_or(1))
        .sum()
}

pub fn fit(s: &str, cols: usize) -> String {
    let mut result = String::new();
    let mut width = 0usize;
    for c in s.chars() {
        let cw = UnicodeWidthChar::width(c).unwrap_or(1);
        if width + cw > cols {
            break;
        }
        result.push(c);
        width += cw;
    }
    let padding = cols.saturating_sub(width);
    result.push_str(&" ".repeat(padding));
    result
}

pub fn right_align_amount(amount: i64, width: usize) -> String {
    let s = format!("{}円", crate::models::format_amount(amount));
    let w = display_width(&s);
    if w >= width {
        s
    } else {
        format!("{}{}", " ".repeat(width - w), s)
    }
}
