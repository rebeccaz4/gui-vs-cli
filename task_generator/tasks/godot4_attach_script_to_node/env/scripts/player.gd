class_name Player
extends CharacterBody2D

@export var speed: float = 200.0

func _physics_process(delta):
	move_and_slide()
