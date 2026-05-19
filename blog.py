from flask import Blueprint, render_template, abort
from models import BlogPost

blog_bp = Blueprint('blog', __name__, url_prefix='/blog')

@blog_bp.route('/')
def index():
    posts = BlogPost.query.order_by(BlogPost.date_published.desc()).all()
    return render_template('blog/list.html', posts=posts)

@blog_bp.route('/<slug>')
def detail(slug):
    post = BlogPost.query.filter_by(slug=slug).first_or_404()
    return render_template('blog/detail.html', post=post)
