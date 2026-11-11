use crate::BASE_URL;
use aidoku::{
	Result,
	alloc::string::String,
	imports::{
		html::{Document, Html},
		js::WebView,
		net::Request,
	},
	prelude::*,
};

/// Use WebKit when Cloudflare blocks the native HTTP client.
pub fn get_html(request: Request) -> Result<Document> {
	let response = request.send()?;
	let html = response.get_html()?;
	let challenged = response.get_header("cf-mitigated").as_deref() == Some("challenge")
		|| html
			.select_first("title")
			.and_then(|el| el.text())
			.is_some_and(|title| title.starts_with("Just a moment"));
	if !challenged {
		return Ok(html);
	}
	let url = response
		.get_url()
		.ok_or_else(|| error!("Missing response URL"))?;
	let webview = WebView::new();
	webview
		.load_blocking(Request::get(&url)?)
		.map_err(|err| error!("Cloudflare WebView load failed: {err:?}"))?;
	let document = webview
		.eval_async(
			r#"
  new Promise(resolve => {
   const deadline = Date.now() + 15000;
   const check = () => {
    const blocked = document.title.startsWith('Just a moment')
     || document.querySelector('#challenge-error-title, #challenge-error-text');
    if (!blocked) return resolve(document.documentElement.outerHTML);
    if (Date.now() >= deadline) return resolve('');
    setTimeout(check, 250);
   };
   check();
  })
 "#,
		)
		.map_err(|err| error!("Cloudflare WebView evaluation failed: {err:?}"))?;
	if document.is_empty() {
		bail!(
			"Cloudflare verification required. Open Asura Scans in Aidoku's browser, complete verification, then retry."
		);
	}
	Ok(Html::parse_with_url(document, &url)?)
}

/// Returns the ID of a manga from a URL.
pub fn get_manga_key(url: &str) -> Option<String> {
	// Asura Scans appends a random string at the end of each series slug
	// The random string is not necessary, along with the trailing '-'

	// remove query parameters
	let path = url.split('?').next().unwrap_or("");

	// find the segment after "series"
	let manga_segment = path
		.split('/')
		.skip_while(|segment| *segment != "comics")
		.nth(1)?;

	// find the last '-' and keep it in the id
	let pos = manga_segment.rfind('-')?;
	Some(manga_segment[..pos].into())
}

/// Returns the ID of a chapter from a URL.
pub fn get_chapter_key(url: &str) -> Option<String> {
	// remove query parameters
	let path = url.split('?').next().unwrap_or("");

	// find the segment after "chapter"
	let chapter_segment = path
		.split('/')
		.skip_while(|segment| *segment != "chapter")
		.nth(1)?;

	// extract only the numeric (and '.') prefix
	let end_pos = chapter_segment
		.find(|c: char| !c.is_numeric() && c != '.')
		.unwrap_or(chapter_segment.len());

	Some(chapter_segment[..end_pos].into())
}

/// Returns full URL of a manga from a manga ID.
pub fn get_manga_url(manga_id: &str) -> String {
	format!("{BASE_URL}/comics/{manga_id}")
}

/// Returns full URL of a chapter from a chapter ID and manga ID.
pub fn get_chapter_url(chapter_id: &str, manga_id: &str) -> String {
	format!("{BASE_URL}/comics/{manga_id}/chapter/{chapter_id}")
}

#[cfg(test)]
mod tests {
	use super::*;
	use aidoku_test::aidoku_test;

	#[aidoku_test]
	fn test_manga_keys() {
		assert_eq!(
			get_manga_key("https://asurascans.com/comics/swordmasters-youngest-son-cb22671f")
				.as_deref(),
			Some("swordmasters-youngest-son")
		);
		assert_eq!(
			get_manga_key(
				"https://asurascans.com/comics/swordmasters-youngest-son-cb22671f?blahblah"
			)
			.as_deref(),
			Some("swordmasters-youngest-son")
		);
		assert_eq!(
			get_manga_key(
				"https://asurascans.com/comics/swordmasters-youngest-son-cb22671f/chapter/1"
			)
			.as_deref(),
			Some("swordmasters-youngest-son")
		);
	}

	#[aidoku_test]
	fn test_chapter_keys() {
		assert_eq!(
			get_chapter_key("https://asurascans.com/comics/swordmasters-youngest-son-cb22671f"),
			None
		);
		assert_eq!(
			get_chapter_key(
				"https://asurascans.com/comics/swordmasters-youngest-son-cb22671f?blahblah"
			),
			None
		);
		assert_eq!(
			get_chapter_key(
				"https://asurascans.com/comics/swordmasters-youngest-son-cb22671f/chapter/1"
			)
			.as_deref(),
			Some("1")
		);
		assert_eq!(
			get_chapter_key("https://asurascans.com/comics/swordmasters-youngest-son/chapter/1")
				.as_deref(),
			Some("1")
		);
	}
}
