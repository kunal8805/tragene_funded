from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from functools import wraps
from models import db, User, BlogPost, Moderator
from datetime import datetime, timezone
import re

admin_blog_bp = Blueprint('admin_blog', __name__, url_prefix='/admin/blog')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check super admin
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user and user.is_admin:
                return f(*args, **kwargs)
        
        # Check moderator
        if 'moderator_id' in session:
            moderator = Moderator.query.get(session['moderator_id'])
            if moderator and moderator.is_active():
                return f(*args, **kwargs)
        
        flash('Please login to access this page.', 'error')
        return redirect(url_for('auth.login'))
    return decorated_function

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text

@admin_blog_bp.route('/')
@admin_required
def list_posts():
    posts = BlogPost.query.order_by(BlogPost.date_published.desc()).all()
    return render_template('admin/blog/list.html', posts=posts)

@admin_blog_bp.route('/create', methods=['GET', 'POST'])
@admin_required
def create():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        slug = request.form.get('slug', '').strip()
        content = request.form.get('content', '').strip()
        meta_description = request.form.get('meta_description', '').strip()
        
        if not title or not content or not meta_description:
            flash('Title, content, and meta description are required.', 'danger')
            return render_template('admin/blog/form.html', post=None)
            
        if not slug:
            slug = slugify(title)
            
        existing = BlogPost.query.filter_by(slug=slug).first()
        if existing:
            flash(f'A post with slug "{slug}" already exists. Please choose a different title or slug.', 'danger')
            return render_template('admin/blog/form.html', post=None)
            
        new_post = BlogPost(
            title=title,
            slug=slug,
            content=content,
            meta_description=meta_description,
            date_published=datetime.now(timezone.utc)
        )
        
        try:
            db.session.add(new_post)
            db.session.commit()
            flash('Blog post created successfully!', 'success')
            return redirect(url_for('admin_blog.list_posts'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating post: {str(e)}', 'danger')
            return render_template('admin/blog/form.html', post=None)
            
    return render_template('admin/blog/form.html', post=None)

@admin_blog_bp.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@admin_required
def edit(post_id):
    post = BlogPost.query.get_or_404(post_id)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        slug = request.form.get('slug', '').strip()
        content = request.form.get('content', '').strip()
        meta_description = request.form.get('meta_description', '').strip()
        
        if not title or not content or not meta_description:
            flash('Title, content, and meta description are required.', 'danger')
            return render_template('admin/blog/form.html', post=post)
            
        if not slug:
            slug = slugify(title)
            
        existing = BlogPost.query.filter(BlogPost.slug == slug, BlogPost.id != post.id).first()
        if existing:
            flash(f'A post with slug "{slug}" already exists. Please choose a different title or slug.', 'danger')
            return render_template('admin/blog/form.html', post=post)
            
        post.title = title
        post.slug = slug
        post.content = content
        post.meta_description = meta_description
        
        try:
            db.session.commit()
            flash('Blog post updated successfully!', 'success')
            return redirect(url_for('admin_blog.list_posts'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating post: {str(e)}', 'danger')
            return render_template('admin/blog/form.html', post=post)
            
    return render_template('admin/blog/form.html', post=post)

@admin_blog_bp.route('/delete/<int:post_id>', methods=['POST'])
@admin_required
def delete(post_id):
    post = BlogPost.query.get_or_404(post_id)
    try:
        db.session.delete(post)
        db.session.commit()
        flash('Blog post deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting post: {str(e)}', 'danger')
    return redirect(url_for('admin_blog.list_posts'))