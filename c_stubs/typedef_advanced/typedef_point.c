typedef double Coordinate;
typedef struct
{
    Coordinate x;
    Coordinate y;
} Point;

Coordinate point_distance(Point first, Point second);

int main(void)
{
    Point first = {0.0, 0.0};
    Point second = {3.0, 4.0};
    Coordinate distance;

    distance = point_distance(first, second);

    return 0;
}

// Return the distance between two points.
Coordinate point_distance(Point first, Point second)
{
